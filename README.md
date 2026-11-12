# ue-kit

**ภาษาอังกฤษ** - An MCP server (Python, stdio) that lets an agent — Hermes or Claude — assemble buildings in the **open
Unreal Editor** by saying how parts sit on each other, and then place the results as a town. It computes
transforms from the meshes' real sizes, checks the result, and hands back photos. It talks to the editor's
own MCP server at `http://127.0.0.1:8000/mcp`.

**ภาษาไทย** - เซิร์ฟเวอร์ MCP (Python, stdio) ที่ช่วยให้ agent (Hermes หรือ Claude) สามารถประกอบอาคารใน **Unreal Editor** ที่เปิดอยู่ โดยบอกว่าจะวางส่วนต่าง ๆ บนกันอย่างไร แล้ววางผลลัพธ์เป็นเมือง มันคำนวณ
transform จากขนาดจริงของ mesh, ตรวจสอบผลลัพธ์, และส่งภาพถ่ายกลับมา มันคุยกับเซิร์ฟเวอร์ MCP ของ editor ที่
`http://127.0.0.1:8000/mcp`

```
python U:/ai_workspace/ue-kit/server.py        # stdio; registered in Hermes' config.yaml and MyHeadLine/.mcp.json
python -m pytest                                # 59 offline tests, no Unreal needed
```

วิธีใช้งาน tools อยู่ ใน skill แบบแชร์ `~/.claude/skills/ue-kit-building/` (SKILL.md และ
`references/town-and-more.md`). ไฟล์นี้เกี่ยวกับโค้ด

## Files

| File | What |
|---|---|
| `server.py` | The MCP tool surface only: argument checks, wording of results. **Changes here need the server restarted** (restart Hermes). |
| `kit.py` | Geometry (`resolve`), checks (`check`, `autofix`), caches, guards, building/rebuilding Blueprints, design store, promote, dress, budget. Hot-reloaded. |
| `shots.py` | Every photo: `look`, labelled thumbnails, `gallery`, `area`. Hot-reloaded. |
| `town.py` | `plan` (pure) → `survey` (line traces) → `place` / `clear`. Hot-reloaded. |
| `ue_client.py` | Tiny JSON-RPC client for the editor's MCP; `batch()` runs a sandboxed script in the editor. Hot-reloaded. |
| `tests/` | Offline: every editor call is blocked and state files are copies (`conftest.offline`). |
| `designs_claude.py`, `gallery.py`, `bp_parts.py`, `test_*.py` in the root | Older command-line scripts, kept; not collected by pytest. |
| `*_job.py`, `terrain_shots.py` | One-off jobs for the Vocaris world map (temporary water, landscape material, terrain photos). They write into real game maps, so they are deliberately **not** tools. |

State (committed, so a bad change can be undone): `designs.json` (parts of every real build — the source of
truth for `check_designs`, `get_design`, `place_town`), `designs_registry.json` (shape signatures for TOO
SIMILAR), `test_spots.json` (one test spot per Blueprint name), `bounds_cache.json` / `openings_cache.json` /
`mesh_stats.json` (measured in the editor; an entry is dropped when its `.uasset` changes), `town_plan.json`
(the last placement). Written through a temp file because two servers may run at once.
Log of everything changed in the editor: `C:\UE\logs\ue-kit\actions.log`.

## Rules the code enforces (`kit.py`)

- Test copies, the doorway probe, deletions and town placement happen only when the open level matches
  `TEST_MAPS`.
- A Blueprint is created only under `SANDBOX`, or where `designs.json` says ue-kit built that name before;
  an existing asset is replaced only if ue-kit built it.
- An existing Blueprint is rebuilt **in place** (components removed and re-added): the asset object stays,
  so copies in other levels survive. Delete-and-create is only the fallback.
- Actors are matched by **exact label** (the editor's search is a substring match) and town actors by tag
  `ue-kit-town`; `remove_actor` only takes a full `<name>_Test` label.
- A dry run of `build_blueprint` makes no editor call that changes anything; doorway data that is not cached
  is reported, not measured.

## Things learned about the editor's MCP (verified here)

- `AssetTools.delete` on an asset that was not loaded yet removes it from memory but leaves the file; a
  second call in a later request removes the file. `kit.build` checks and retries.
- A Blueprint's component is addressed as `<path>.<Name>_C:<Part>_GEN_VARIABLE`; `get_components` only
  accepts a placed actor, so the part names are read from a copy (or a throw-away probe).
- A tool error inside `execute_tool_script` aborts the script; `try/except` in the script does not catch it.
- `get_actor_bounds` includes editor sprites, so an actor's box can start ~100 cm below its meshes.
- There is no tool to set a console variable at run time.
- `CaptureViewport` needs a second capture after a camera jump (Nanite culls against the previous frame).

## Not done

- No connector-based placement for dungeon packs: modules snap with `against:` like house modules do, but
  nothing knows about corridor openings yet.
- `budget` reports repeated meshes; it does not convert them to instanced components.
- Town placement has only been run on the flat test map; the foundation code was exercised with simulated
  ground heights, not on real terrain.
