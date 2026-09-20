# Transition decision table

| Previous shot | Next shot | Named subject overlap | Decision | Reason |
|---|---|---:|---|---|
| Protagonists in council hall | Busy street without protagonists | No | `new_lane_direct_cut` | Establishing insert; no subject must travel |
| Police analyze in station | Criminal escapes in warehouse | No | `parallel_cut` | Parallel narrative lane |
| Character leaves office | Same character already at home later | Yes | `same_subject_ellipsis` | Ordinary relocation is understandable |
| Character walks toward hall exit | Same character rides a dragon inside a storm wall | Yes | `bridge_required` | Mounting, takeoff, and hazardous destination are unexplained |
| Injured character in ambulance | Same character in hospital bed | Yes | `same_subject_ellipsis` | Destination and transport outcome are conventional |
| Dry uninjured character on shore | Same character underwater, bleeding, without diving equipment | Yes | `bridge_required` | Capability, equipment, and injury states jump |
| Detective closes case file | Match cut to criminal closing a suitcase | No | `match_cut_or_montage` | Visual transition joins different subjects intentionally |

## Boundary audit schema

Use this structure when a machine-readable result is needed:

```json
{
  "previous_shot_no": 12,
  "next_shot_no": 13,
  "scene_changed": true,
  "continuing_subjects": ["洛汐", "岚牙"],
  "new_subjects": [],
  "transition_mode": "bridge_required",
  "state_deltas": [
    "洛汐: walking indoors -> airborne in storm",
    "洛汐与岚牙: unestablished rider/mount relation -> joint flight"
  ],
  "evidence": [],
  "minimum_fix": "Establish 洛汐 mounting 岚牙 and 岚牙 taking off; keep 洛汐 explicitly as rider."
}
```

## Evidence that can legalize a jump

- explicit time text such as “later”, “the next morning”, or a dated scene header;
- explicit montage or match-cut instruction;
- a previous action that establishes departure and the next shot clearly establishes an ordinary destination;
- a screenplay line that states arrival, boarding, mounting, takeoff, capture, treatment, or costume change;
- a director-approved ellipsis recorded in transition metadata.

Absence of a bridge is not itself an error. Error requires both a continuing subject and a material unexplained state change.
