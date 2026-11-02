import csv
import json
import tempfile
import unittest
from pathlib import Path

import torch

from backend.app.config import PROJECT_ROOT
from scripts.train_full import choose_resume, inspect_checkpoint, process_lock, stage_resume


class FullTrainingSafetyTests(unittest.TestCase):
    def checkpoint(self,path,data,epoch=0):
        model=torch.nn.Linear(2,2)
        model.names={0:'smoke',1:'fire'}
        torch.save({'ema':model,'epoch':epoch,'optimizer':{'state':{0:{'exp_avg':torch.tensor([.1])}},'param_groups':[{'params':[0]}]},'scaler':{'scale':65536.},'updates':1,'train_args':{'epochs':50,'data':str(data)},'train_metrics':{'fitness':.1},'best_fitness':.1,'train_results':{'epoch':[1],'train/box_loss':[1.2]}},path)

    def test_corrupt_last_falls_back_and_restores_checkpoint_history(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT/'.tmp',prefix='resume-test-') as folder:
            run=Path(folder)
            (run/'input').mkdir()
            weights=run/'training/weights'
            weights.mkdir(parents=True)
            (run/'state.json').write_text(json.dumps({'status':'failed'}))
            (weights/'last.pt').write_bytes(b'interrupted write')
            self.checkpoint(weights/'epoch0.pt',run/'input/data.yaml')
            (weights/'epoch3.pt').write_bytes(b'bad old future checkpoint')
            (run/'training/results.csv').write_text('epoch,train/box_loss\n1,1.2\n2,1.1\n')
            (run/'epoch-times.jsonl').write_text('{"epoch":1}\n{"epoch":2}\n')
            selected=choose_resume(run)
            self.assertEqual(selected.name,'epoch0.pt')
            staged=stage_resume(run,selected)
            self.assertTrue(inspect_checkpoint(staged)['resumable'])
            with (run/'training/results.csv').open() as stream:
                self.assertEqual(len(list(csv.DictReader(stream))),1)
            self.assertFalse((weights/'epoch3.pt').exists())
            self.assertTrue((staged.parent/'weights/last.pt').exists())
            self.assertTrue(inspect_checkpoint(weights/'best.pt')['resumable'])
            self.assertEqual(len((run/'epoch-times.jsonl').read_text().splitlines()),1)

    def test_inference_checkpoint_is_rejected_for_resume(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT/'.tmp',prefix='stripped-test-') as folder:
            path=Path(folder)/'inference.pt'
            self.checkpoint(path,Path(folder)/'data.yaml',epoch=-1)
            with self.assertRaises(RuntimeError): inspect_checkpoint(path)
            self.assertFalse(inspect_checkpoint(path,require_resume=False)['resumable'])

    def test_os_lock_rejects_duplicate_worker(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT/'.tmp',prefix='lock-test-') as folder:
            lock=Path(folder)/'run.lock'
            with process_lock(lock):
                with self.assertRaises(RuntimeError):
                    with process_lock(lock): pass
            with process_lock(lock): pass


if __name__=='__main__':
    unittest.main()
