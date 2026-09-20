---
name: subject-aware-scene-transitions
description: Audit and plan adjacent storyboard scene changes by distinguishing continuing subjects from new narrative lanes. Use when splitting chapters into shots, reviewing cross-scene continuity, deciding whether a bridge shot is required, allowing parallel cuts between different characters, or preserving character transport, riding, equipment, injury, and capability states across a scene boundary.
---

# Subject-Aware Scene Transitions

Evaluate scene boundaries by narrative subject, not by location change alone.

## Workflow

1. Compare the named characters in the two adjacent shots.
2. If no named character continues, allow a direct cut. Treat it as a new narrative lane, parallel cut, reaction cut, or environment insert.
3. If characters continue, compare only their persistent state:
   - location and travel mode;
   - posture and physical capability;
   - rider/carrier/vehicle relationship;
   - costume, equipment, held props, injury, restraint, and wetness;
   - story time when explicitly known.
4. Allow a direct cut when the omitted travel is ordinary and the destination state is immediately understandable.
5. Require explicit evidence or a bridge beat when the new state needs an enabling action, changes a relationship, contradicts capability, or would confuse causal order.
6. Never carry the previous scene's lighting, weather, architecture, or camera axis into the new scene. Carry only continuing character and story state.
7. When a bridge is required, add the smallest sufficient beat. Do not mechanically show every door, corridor, vehicle entry, or journey.

## Output Decision

Choose exactly one:

- `new_lane_direct_cut`: no continuing named subject; no bridge required.
- `parallel_cut`: another subject or faction continues elsewhere; no bridge required.
- `same_subject_ellipsis`: the same subject appears after an understandable ordinary relocation; no bridge required.
- `explicit_time_jump`: the script states a time jump; no bridge required.
- `match_cut_or_montage`: the script or directing plan intentionally compresses the transition.
- `bridge_required`: a continuing subject has an unexplained enabling-state or capability jump.

For detailed boundary examples and the decision table, read
[references/transition-decision-table.md](references/transition-decision-table.md).

## Hard Rules

- Do not require transitions merely because the location changes.
- Do not reject police-station-to-criminal-hideout cuts when the named subjects differ.
- Do not reject a protagonist scene followed by an empty street establishing shot.
- Do reject an on-foot subject appearing airborne without established flight, vehicle, mount, time jump, or transition evidence.
- Do reject collective wording that gives every character one member's capability. Write “the dragon carries the rider through the storm,” not “the rider and dragon flap their wings.”
- Keep scene continuity and character continuity separate: reset scene appearance; preserve continuing character facts.
