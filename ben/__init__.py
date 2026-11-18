"""ben — an engagement fact graph for autonomous agents (package root).

Re-exports the public surface (and the names the hook/tests rely on) so
`import ben` keeps working exactly like the old single-file module.
"""
from __future__ import annotations

from ben.consts import (  # noqa: F401
    AI_CHANNEL_NAME, DATA_KEY_RE, DEFAULT_STORE, FACT_KINDS, GOAL_ID, LOCK_NAME, PEERS_FILE, PEER_NAME_RE, _UNSET, _VALID_NODE_ID_RE, __version__,
)
from ben import config as config  # noqa: F401
from ben.core.schema import (  # noqa: F401
    _check_conclusion_permission, _node_schema_errors, _read_node, _validate_lookup_id,
    normalize_fact_data, normalize_fact_kind, parse_kv_pairs
)
from ben.core.io import (  # noqa: F401
    _CONTROL_CHAR_RE, _prompt_inline, _read_node_files,
    _scrub_inline, atomic_write_json, now_iso, read_json
)
from ben.core.errors import (  # noqa: F401
    FGError
)
from ben.core.store import (  # noqa: F401
    Store
)
from ben.core.graph import (  # noqa: F401
    build_graph_view, frontier, is_open, is_ready, validate_graph
)
from ben.report.status import (  # noqa: F401
    _RECALL_TOKEN_RE, render_status
)
from ben.core.recall import (  # noqa: F401
    _recall_score, _recall_tokenize, recall
)
from ben.agents.prompt import (  # noqa: F401
    _hint_brief, _intent_brief, _replace_placeholders, _to_yaml_like,
    render_graph_text, render_history_block, render_intent_prompt, render_prompt,
    render_recall
)
from ben.llm.jsonx import (  # noqa: F401
    _QUOTA_ERROR_RE, _extract_first_balanced, extract_json_object
)
from ben.llm.keys import (  # noqa: F401
    _is_quota_error, _load_key_pool, _rotate_key, _seed_key_from_pool
)
from ben.llm.runner import (  # noqa: F401
    _run_engine_once, run_claude
)
from ben.commands.util import (  # noqa: F401
    _assert_safe_store_root, _read_doc_arg, _resolve_templates_dir, parse_from
)
from ben.commands.graph_cmds import (  # noqa: F401
    cmd_fact, cmd_frontier, cmd_graph, cmd_hint, cmd_init, cmd_intent, cmd_pick,
    cmd_status, cmd_validate
)
from ben.commands.arena_cmds import (  # noqa: F401
    _arena_client, _find_flag_fact, _load_arena_module, cmd_arena, cmd_flag
)
from ben.commands.kb_cmds import (  # noqa: F401
    _kb, _load_kb_module, cmd_kb
)
from ben.commands.bench import (  # noqa: F401
    _arena_client_for_root, _bench_parallel, _bench_prepare_graph, _bench_store,
    _bench_submit_recorded, cmd_bench
)
from ben.commands.commander import (  # noqa: F401
    _board_summary, _command_fleet_cfg, _parse_command_payload, cmd_command, render_board
)
from ben.commands.fleet import (  # noqa: F401
    FLEET_FILE, FLEET_TEMPLATE, _active_workers, _fire_worker, _fleet_load,
    _fleet_pane_command, _hire_worker, _ben_engine_prefix, cmd_fleet
)
from ben.commands.misc import (  # noqa: F401
    _edit_via_editor, cmd_doc, cmd_recall, cmd_show, cmd_sweep
)
from ben.commands.dispatch import (  # noqa: F401
    cmd_claim, cmd_complete, cmd_confirm, cmd_dispatch, cmd_done, cmd_release
)
from ben.agents.factory import (  # noqa: F401
    _agents_system_prompt, _apply_blindspot, _apply_brainstorm, _apply_reason, _classify_reason_payload,
    _run_blindspot, _run_brainstorm, _load_template, _looks_reason, _parse_explore_payload,
    _parse_verify_payload, _worker_id, cmd_brainstorm_pick
)
from ben.agents.dispatch import (  # noqa: F401
    _dispatch_explore, _dispatch_reason, _dispatch_verify,
)
from ben.commands.setup import (  # noqa: F401
    _AGENTS_MARKER, _AGENTS_SPEC, _hook_script_path, _load_settings_patch, _skill_root,
    cmd_setup, cmd_teardown
)
from ben.web.view import (  # noqa: F401
    _VIEW_TEMPLATE, _load_view_template, _render_static_html, _try_open, _try_open_url,
    _view_serve, _view_template_path, cmd_view
)
from ben.commands.auto import (  # noqa: F401
    _graph_signature, _run_explore_raw, _run_reason_raw, _run_verify_raw, cmd_auto,
)
from ben.core.timebudget import deadline_from_args, format_time_budget  # noqa: F401
from ben.commands.verify_cmds import cmd_verify  # noqa: F401
from ben.commands.peers import (  # noqa: F401
    _default_peers, _load_peers, _peers_path, _save_peers, cmd_capture, cmd_peers,
    cmd_send
)
from ben.runtime.agents import (  # noqa: F401
    AgentRegistry, fleet_registry_root
)
from ben.cli import (  # noqa: F401
    build_parser, main
)
