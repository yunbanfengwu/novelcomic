-- 连续主体感知转场：标准 agentskills.io Skill + 数字员工绑定。
-- 技能正文与 references 文件均可在系统管理中查看；本地源码位于
-- skills/subject-aware-scene-transitions/。
INSERT INTO skill_packages(
    slug,name,description,version,source_url,license,skill_md,manifest,status
) VALUES (
    'subject-aware-scene-transitions',
    '连续主体感知转场',
    '区分连续角色与新叙事线，判断跨场景是否需要过渡，并保护骑乘、载具、装备、伤势与能力状态。',
    '1.0.0',
    'repo://skills/subject-aware-scene-transitions',
    'MIT',
    $$---
name: subject-aware-scene-transitions
description: Audit and plan adjacent storyboard scene changes by distinguishing continuing subjects from new narrative lanes. Use when splitting chapters into shots, reviewing cross-scene continuity, deciding whether a bridge shot is required, allowing parallel cuts between different characters, or preserving character transport, riding, equipment, injury, and capability states across a scene boundary.
---

# Subject-Aware Scene Transitions

Evaluate scene boundaries by narrative subject, not by location change alone.

1. Compare named characters in adjacent shots.
2. If no named character continues, allow a direct new-lane, parallel, reaction, or environment cut.
3. If characters continue, carry location/travel mode, rider-carrier relationship, costume,
   equipment, held props, injury, restraint, wetness, and established capability.
4. Reset the new scene's lighting, weather, architecture, palette, and camera axis.
5. Allow ordinary understandable relocation to be omitted.
6. Require the smallest sufficient bridge or explicit evidence only for an unexplained enabling
   action, relationship change, equipment/injury change, or capability contradiction.
7. Never give a rider the mount's wings or locomotion. Write “the dragon carries the rider through
   the storm,” not “the rider and dragon flap their wings.”

Choose one decision:
- new_lane_direct_cut: no continuing named subject.
- parallel_cut: another subject or faction continues elsewhere.
- same_subject_ellipsis: ordinary understandable relocation.
- explicit_time_jump: the script states a time jump.
- match_cut_or_montage: directing intentionally compresses the transition.
- bridge_required: a continuing subject has an unexplained material state jump.

Read references/transition-decision-table.md for examples.
$$,
    '{"format":"agentskills.io","local_path":"skills/subject-aware-scene-transitions","category":"storyboard-continuity"}'::jsonb,
    'installed'
)
ON CONFLICT(slug) DO UPDATE SET
    name=excluded.name,description=excluded.description,version=excluded.version,
    source_url=excluded.source_url,license=excluded.license,skill_md=excluded.skill_md,
    manifest=excluded.manifest,status='installed',updated_at=now();

INSERT INTO skill_package_files(skill_id,path,content)
SELECT id,'references/transition-decision-table.md',$$Transition decision table:

| Previous | Next | Subject overlap | Decision |
|---|---|---:|---|
| Protagonists in council hall | Busy street without protagonists | No | new_lane_direct_cut |
| Police analyze in station | Criminal escapes elsewhere | No | parallel_cut |
| Character leaves office | Same character at home later | Yes | same_subject_ellipsis |
| Character walks toward hall exit | Same rider and dragon already flying in storm | Yes | bridge_required |
| Injured character in ambulance | Same character in hospital bed | Yes | same_subject_ellipsis |
| Dry character on shore | Same character underwater bleeding without equipment | Yes | bridge_required |

Evidence may be an explicit time jump, montage/match cut, arrival, boarding, mounting, takeoff,
capture, treatment, costume change, or a director-approved ellipsis. Absence of a bridge is not
itself an error: both a continuing named subject and a material unexplained state change are needed.
$$
FROM skill_packages WHERE slug='subject-aware-scene-transitions'
ON CONFLICT(skill_id,path) DO UPDATE SET content=excluded.content;

INSERT INTO agent_template_skills(agent_template_id,skill_id)
SELECT a.id,s.id FROM agent_templates a CROSS JOIN skill_packages s
WHERE a.code IN ('director','continuity-supervisor')
  AND s.slug='subject-aware-scene-transitions'
ON CONFLICT DO NOTHING;

INSERT INTO agent_skill_bindings(agent_id,skill_id)
SELECT a.id,s.id FROM agents a CROSS JOIN skill_packages s
WHERE a.code IN ('director','continuity-supervisor')
  AND s.slug='subject-aware-scene-transitions'
ON CONFLICT DO NOTHING;
