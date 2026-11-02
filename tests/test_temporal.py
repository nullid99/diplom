import unittest
from backend.app.temporal import TemporalConfig, TemporalEvents, Zone, allowed


def detection(x=.1,kind='smoke'):
    return dict(class_name=kind,confidence=.8,xyxy=[x,.1,x+.1,.2])


class TemporalTests(unittest.TestCase):
    def tracker(self,**kw): return TemporalEvents(TemporalConfig(**kw))

    def test_short_single_detection_never_confirms(self):
        tracker=self.tracker()
        self.assertEqual(tracker.update(0,[detection()]),[])
        self.assertEqual(tracker.update(3,[]),[])
        self.assertEqual(tracker.finish(4,'eof'),[])

    def test_stable_then_absence_has_four_distinct_times(self):
        tracker=self.tracker()
        for t in [0,.5]: self.assertEqual(tracker.update(t,[detection()]),[])
        confirmed=tracker.update(1,[detection()])[0]
        self.assertEqual(confirmed['confirmed_seconds'],1)
        self.assertEqual(tracker.update(2,[]),[])
        closed=tracker.update(3,[])[0]
        self.assertEqual((closed['start_seconds'],closed['confirmed_seconds'],closed['last_seen_seconds'],closed['closed_seconds']),(0,1,1,3))
        self.assertEqual(closed['closure_reason'],'absence')

    def test_duplicate_boxes_are_one_time_observation(self):
        tracker=self.tracker()
        self.assertEqual(tracker.update(0,[detection()]*8),[])
        self.assertEqual(len(tracker.tracks),1)
        self.assertEqual(tracker.update(.5,[detection()]*8),[])
        self.assertEqual(len(tracker.update(1,[detection()]*8)),1)

    def test_spatially_separate_regions_and_classes(self):
        tracker=self.tracker()
        boxes=[detection(.1),detection(.8),detection(.1,'fire')]
        tracker.update(0,boxes);tracker.update(.5,boxes)
        events=tracker.update(1,boxes)
        self.assertEqual(len(events),3)
        self.assertEqual(len({e['track_key'] for e in events}),3)

    def test_one_detection_cannot_update_two_tracks(self):
        tracker=self.tracker(min_span_seconds=.5,min_hits=2)
        tracker.update(0,[detection(.1),detection(.25)])
        events=tracker.update(.5,[detection(.17)])
        self.assertEqual(len(events),1)

    def test_gaps_within_timeout_merge_episode(self):
        tracker=self.tracker()
        tracker.update(0,[detection()]);tracker.update(.5,[]);tracker.update(1,[detection()])
        event=tracker.update(1.5,[detection()])[0]
        self.assertEqual(event['start_seconds'],0)
        tracker.update(2,[])
        self.assertEqual(tracker.update(2.5,[detection()]),[])
        self.assertEqual(len(tracker.finish(3,'eof')),1)

    def test_long_gap_starts_new_episode(self):
        tracker=self.tracker()
        for t in [0,.5,1]: tracker.update(t,[detection()])
        closed=tracker.update(4,[detection()])
        self.assertEqual(closed[0]['closure_reason'],'absence')
        self.assertEqual(tracker.finish(4.5,'eof'),[])

    def test_varying_intervals_and_window(self):
        tracker=self.tracker(window_seconds=2)
        self.assertEqual(tracker.update(.1,[detection()]),[])
        self.assertEqual(tracker.update(.7,[detection()]),[])
        self.assertEqual(len(tracker.update(1.4,[detection()])),1)
        tracker=self.tracker(min_span_seconds=1)
        for t in [0,.01,.02]: self.assertEqual(tracker.update(t,[detection()]),[])

    def test_eof_cancellation_and_failure(self):
        for reason,status in [('eof','completed'),('cancelled','interrupted'),('failed','interrupted')]:
            with self.subTest(reason=reason):
                tracker=self.tracker()
                for t in [0,.5,1]: tracker.update(t,[detection()])
                event=tracker.finish(1.2,reason)[0]
                self.assertEqual(event['automatic_status'],status)
                self.assertEqual(event['last_seen_seconds'],1)
                self.assertEqual(event['closed_seconds'],1.2)

    def test_inclusion_center_and_exclusion_priority(self):
        include=Zone(id='i',name='Include',mode='include',x1=.1,y1=.1,x2=.6,y2=.6)
        exclude=Zone(id='e',name='Exclude',mode='exclude',x1=.3,y1=.3,x2=.4,y2=.4)
        self.assertTrue(allowed([0,0,.3,.3],[include]))
        self.assertFalse(allowed([.3,.3,.4,.4],[include,exclude]))
        self.assertTrue(allowed([.8,.8,.9,.9],[exclude]))
        self.assertFalse(allowed([.8,.8,.9,.9],[include]))

    def test_frequency_and_time_validation(self):
        with self.assertRaises(ValueError): TemporalConfig().validate_frequency(.1)
        with self.assertRaises(ValueError): TemporalConfig(window_seconds=.5,min_span_seconds=1)
        tracker=self.tracker();tracker.update(1,[])
        with self.assertRaises(ValueError): tracker.update(1,[])


if __name__=='__main__': unittest.main()
