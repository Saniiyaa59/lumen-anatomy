import { displayName } from '../registry.ts'
import { useSelection } from '../selection/useSelection.ts'

const mm = (metres: number) => `${(metres * 1000).toFixed(1)} mm`

/**
 * Shows where the last click landed while exploring: the exact point, and for
 * a vessel which piece of it and how far along.
 */
export default function PositionReadout() {
  const { clickLog } = useSelection()
  const click = clickLog.at(-1)
  if (!click?.place) return null
  const { point, vessel } = click.place
  const pieceNumber = vessel ? Number(vessel.pieceId.split('.').at(-1)) : 0

  return (
    <section className="readout" aria-label="Where you clicked">
      <h2>{displayName(click.structure_id)}</h2>
      {vessel ? (
        <>
          <p className="readout-main">{mm(vessel.fromStart)} from where it begins</p>
          <p>
            {pieceNumber === 0 ? 'Main trunk' : `Branch ${pieceNumber}`}, {mm(vessel.along)} along it
          </p>
          <p>Click was {mm(vessel.offset)} from the centre line</p>
        </>
      ) : (
        <p>Not a vessel, so no position along it</p>
      )}
      <p className="readout-point">Point: {point.map((value) => (value * 1000).toFixed(1)).join(', ')} mm</p>
    </section>
  )
}
