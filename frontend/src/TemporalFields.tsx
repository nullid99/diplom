export type Temporal = { window_seconds: number; min_hits: number; min_span_seconds: number; absence_seconds: number; match_iou: number; center_distance: number; clip_before_seconds: number; clip_after_seconds: number }
export const temporalDefaults: Temporal = { window_seconds: 3, min_hits: 3, min_span_seconds: 1, absence_seconds: 2, match_iou: .1, center_distance: .12, clip_before_seconds: 2, clip_after_seconds: 3 }
const fields: [keyof Temporal, string, number, number, number][] = [
  ['window_seconds', 'Вікно підтвердження, с', .1, 60, .1], ['min_hits', 'Мінімум різних кадрів', 2, 120, 1],
  ['min_span_seconds', 'Мінімальна тривалість ознак, с', .05, 60, .05], ['absence_seconds', 'Завершення без ознак, с', .1, 120, .1],
  ['match_iou', 'Мінімальний IoU', .01, 1, .01], ['center_distance', 'Близькість центрів (частка кадру)', .001, .5, .001],
  ['clip_before_seconds', 'Фрагмент до підтвердження, с', 0, 15, .1], ['clip_after_seconds', 'Фрагмент після підтвердження, с', .1, 15, .1],
]
export function TemporalFields({ value, onChange }: { value: Temporal; onChange: (value: Temporal) => void }) {
  return <div className="settings-grid temporal-fields">{fields.map(([key,label,min,max,step]) => <label key={key}>{label}<input required type="number" min={min} max={max} step={step} value={Number.isFinite(value[key]) ? value[key] : ''} onChange={event => onChange({ ...value, [key]: event.target.valueAsNumber })} /></label>)}</div>
}
