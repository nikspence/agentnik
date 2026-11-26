import contextlib
import io
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from agentnik.code_terminal import drive_run
from agentnik.code_stream import visible_prefix


def pdf_fixture():
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 100 Td (Headless PDF fixture) Tj ET")
    page[NameObject("/Contents")] = stream
    return writer


class TerminalRunTests(unittest.TestCase):
    def test_resume_snapshot_keeps_raw_prompts_and_separate_history_bounds(self):
        from agentnik.code_history import resume_snapshot

        records = [
            {"coding_models": {"model": {"connection": "Fixture", "model": "fixture"}},
             "code_activity": [{"kind": "prompt", "text": f"/task {index}"}]}
            for index in reversed(range(110))
        ]
        snapshot = resume_snapshot(records)
        self.assertEqual(snapshot.prompt_history, tuple(f"/task {i}" for i in range(10, 110)))
        self.assertEqual(snapshot.activity, tuple(f"/task {i}" for i in range(90, 110)))
        self.assertEqual((snapshot.connection, snapshot.model), ("Fixture", "fixture"))
        with self.assertRaisesRegex(ValueError, "Choose a saved session"):
            resume_snapshot([])

    def test_terminal_can_recover_from_stale_image_setup_without_manual_config(self):
        from agentnik.code_settings import configure_code
        from agentnik.code_terminal import load_run_settings
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            store = Store(Path(directory))
            try:
                store.save_connection("Code", {"url": "https://example.org/v1", "model": "code"})
                store.config["settings"]["image_generation"] = {
                    "enabled": True, "connection": "Missing", "model": "image", "endpoint": "",
                }
                store.flush()
                with self.assertRaisesRegex(ValueError, "/settings image off to run without generation"):
                    load_run_settings(directory, "Code", "")
                configure_code(store, ["image", "off"])
                connection, _, _, options, _ = load_run_settings(directory, "Code", "")
                self.assertEqual(connection["model"], "code")
                self.assertNotIn("image_config", options)
            finally:
                store.db.close()

    def test_terminal_image_status_flags_stale_or_invalid_setup_without_contacting_provider(self):
        from agentnik.code_settings import configure_code
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            store = Store(Path(directory))
            try:
                store.save_connection("Images", {"url": "https://images.example/v1", "model": "image"})
                settings = store.config["settings"]
                with patch("agentnik.core.environment_connections", return_value={}), \
                        patch("agentnik.core.open_request") as request, patch.object(store, "flush") as flush:
                    for name, endpoint, invalid in (
                        ("Missing", "", True), ("Images", "https://other.example/images", True),
                        ("Images", "", False),
                    ):
                        settings["image_generation"] = {
                            "enabled": True, "connection": name, "model": "image", "endpoint": endpoint,
                        }
                        status = configure_code(store, ["image"])
                        self.assertEqual("The saved image setup is unavailable or invalid" in status, invalid)
                    request.assert_not_called()
                    flush.assert_not_called()
            finally:
                store.db.close()

    def test_terminal_decision_status_reports_an_unavailable_saved_advisor(self):
        from agentnik.code_settings import configure_code
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            store = Store(Path(directory))
            try:
                store.config["settings"].update(
                    decision_advice_enabled=True,
                    decision_model={"connection": "Missing fixture", "model": "advisor"},
                )
                with patch("agentnik.core.environment_connections", return_value={}), \
                        patch.object(store, "flush") as flush:
                    status = configure_code(store, ["decision"])
                    self.assertIn("The saved advisor is unavailable", status)
                    self.assertIn("/settings decision set", status)
                    flush.assert_not_called()
            finally:
                store.db.close()

    def test_project_context_resume_skips_machine_records_but_not_failed_project_turns(self):
        from agentnik.code_history import project_context_for_resume

        binding = {"model": {"connection": "Fixture", "model": "first"}}
        context = {"task": "Project task", "answer": "Project result"}
        prior = {"coding_models": binding, "code_state": "completed", "coding_context": context}
        machine = {"coding_models": binding, "coding_file_scope": "machine", "code_state": "completed"}
        other = dict(machine, coding_models={"model": {"connection": "Other", "model": "second"}})
        self.assertEqual(project_context_for_resume([machine, prior]), context)
        self.assertIsNone(project_context_for_resume([other, prior]))
        self.assertIsNone(project_context_for_resume([machine, dict(prior, code_state="failed"), prior]))

    def test_resumed_machine_goal_requires_machine_scope_before_continuing(self):
        self.check_resumed_machine_goal(confirm=False)

    def test_confirmed_machine_goal_sends_saved_evidence_without_replaying_actions(self):
        self.check_resumed_machine_goal(confirm=True)

    def check_resumed_machine_goal(self, confirm):
        import json
        from unittest.mock import Mock
        from test_code_agent import call
        from test_compat_tools import chat
        from test_routing import Wire
        from agentnik import cli, core
        from agentnik.code_history import CodeHistory
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root, data = base / "project", base / "data"
            root.mkdir()
            session = str(uuid4())
            store = Store(data)
            try:
                store.save_connection("Other", {"url": "https://example.org/v1", "model": "other"})
                store.save_connection("Fixture", {"url": "https://example.org/v1", "model": "fixture", "stream": False})
                history = CodeHistory(store, root)
                record, task = history.start("Fixture", {"model": "fixture"}, "Review machine logs", session,
                                             goal=True, machine_scope=True)
                history.finish(record, task, {"status": "cancelled", "text": "Stopped diagnostic."},
                               save_context=False)
                self.assertEqual(history.list(session)[0]["coding_file_scope"], "machine")
                followup, prompt = history.start("Fixture", {"model": "fixture"}, "Check project status", session)
                history.finish(followup, prompt, {"status": "completed", "text": "Checked."})
            finally:
                store.db.close()

            composer = Mock()
            composer.prompt.side_effect = ["/sessions", "/continue", "/scope machine", "/connection Other",
                                           "/continue", "/connection Fixture", "/permissions allow-all",
                                           "/settings limits all unlimited", "/continue", "/exit"]
            done = call("set_goal_status", {"status": "completed", "detail": "Current state reviewed."})
            argv = ["agentnik", "code", str(root), "--data-dir", str(data), "--resume", session]
            with patch("sys.argv", argv), patch("sys.stdin.isatty", return_value=True), \
                    patch("agentnik.code_composer.create_composer", return_value=composer), \
                    patch("builtins.input", return_value="y" if confirm else "") as confirmation, \
                    patch.object(core, "open_request", side_effect=[Wire(chat(calls=[done], finish="tool_calls"), False),
                                                                   Wire(chat("Current state reviewed."), False)]) as request, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(), 0)
            self.assertIn("That goal ran in machine scope. Use /scope machine before continuing.", output.getvalue())
            self.assertIn("[Saved turn used machine scope]", output.getvalue())
            self.assertIn(f"{session}  completed [current] [goal: cancelled]", output.getvalue())
            self.assertIn("Review machine logs", output.getvalue())
            self.assertIn("That goal used connection 'Fixture'.", output.getvalue())
            self.assertIn("Continue using connection 'Fixture', model 'fixture', in machine scope with permissions allow-all.",
                          output.getvalue())
            self.assertIn("Run budgets · rounds: unlimited · requests: unlimited · tool calls: unlimited · seconds: unlimited",
                          output.getvalue())
            self.assertIn("Goal budgets · steps: unlimited · seconds: unlimited", output.getvalue())
            confirmation.assert_called_once_with("Continue this goal with fresh limits? [y/N] ")
            if confirm:
                self.assertEqual(request.call_count, 2)
                body = request.call_args_list[0].args[2]
                messages = json.dumps(body["messages"])
                self.assertIn("Review machine logs", messages)
                self.assertIn("Stopped diagnostic.", messages)
                self.assertIn("do not repeat uncertain actions", messages)
                self.assertNotIn("Check project status", messages)
                tools = {tool["function"]["name"]: tool["function"] for tool in body["tools"]}
                self.assertIn("machine_read_file", tools)
                for name, tool in tools.items():
                    if name.startswith("machine_"):
                        description = tool["parameters"]["properties"]["path"]["description"]
                        self.assertTrue(description.startswith("Explicit absolute path"), (name, description))
                self.assertIn("Project-relative", tools["read_file"]["parameters"]["properties"]["path"]["description"])
                for name in ("run_shell", "run_tests"):
                    description = tools[name]["parameters"]["properties"]["path"]["description"]
                    self.assertIn("Project-relative working directory, even in machine scope", description)
            else:
                request.assert_not_called()

    def test_switching_scope_pauses_and_restores_project_context(self):
        import json
        from unittest.mock import Mock
        from agentnik import cli, core
        from agentnik.storage import Store
        from test_compat_tools import chat
        from test_routing import Wire

        with TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root, data = base / "project", base / "data"
            root.mkdir()
            store = Store(data)
            try:
                store.save_connection("Fixture", {"url": "https://example.org/v1", "model": "fixture", "stream": False})
            finally:
                store.db.close()
            composer = Mock()
            composer.prompt.side_effect = [
                "/connection Fixture", "Initial project task", "/scope machine", "/context",
                "Machine diagnostic task", "/scope project", "Follow up on project",
                "/scope machine", "Last machine task", "/exit",
            ]
            answers = iter(("Prior project answer fixture", "Machine-only answer fixture", "Project follow-up",
                            "Last machine answer fixture", "Resumed project answer"))
            bodies = []

            def send(connection, url, body, timeout):
                bodies.append(json.dumps(body))
                return Wire(chat(next(answers)), False)

            argv = ["agentnik", "code", str(root), "--data-dir", str(data)]
            with patch("sys.argv", argv), patch("sys.stdin.isatty", return_value=True), \
                    patch("agentnik.code_composer.create_composer", return_value=composer), \
                    patch.object(core, "open_request", side_effect=send), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(), 0)
                self.assertEqual(len(bodies), 4)
                argv.extend(("--resume", "latest"))

                def resumed_prompt():
                    self.assertEqual(len(bodies), 4, "Reopening a session must not replay a request")
                    composer.prompt.side_effect = ["/exit"]
                    return "Continue after reopening"

                composer.prompt.side_effect = resumed_prompt
                self.assertEqual(cli.main(), 0)
            self.assertIn("Project context is paused in machine scope.", output.getvalue())
            self.assertEqual(len(bodies), 5)
            self.assertNotIn("Prior project answer fixture", bodies[1])
            self.assertNotIn("Machine-only answer fixture", bodies[2])
            self.assertIn("Prior project answer fixture", bodies[2])
            self.assertIn("Project follow-up", bodies[4])
            self.assertNotIn("Last machine answer fixture", bodies[4])
            self.assertNotIn("machine_read_file", bodies[4])

    def test_connection_export_is_portable_and_refuses_to_overwrite(self):
        from agentnik.cli import export_connection_settings, import_connection_settings
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = Store(root / "source"), Store(root / "destination")
            try:
                source.save_connection("Fixture", {"url": "https://example.org/v1", "model": "fixture",
                                                    "stream": False, "api_key": "synthetic"}, plaintext=True)
                path = root / "portable settings.json"
                with contextlib.redirect_stdout(io.StringIO()), patch("builtins.input", return_value="y"):
                    export_connection_settings(source, f'"{path}"')
                    content = path.read_bytes()
                    self.assertNotIn(b"synthetic", content)
                    self.assertNotIn(b"_capability_scope", content)
                    with self.assertRaisesRegex(ValueError, "already exists"):
                        export_connection_settings(source, str(path))
                    self.assertEqual(path.read_bytes(), content)
                    import_connection_settings(destination, str(path))
                imported = destination.config["connections"]["Fixture"]
                self.assertEqual(imported["model"], "fixture")
                self.assertFalse(imported["stream"])
                self.assertNotIn("api_key", imported)
            finally:
                source.db.close()
                destination.db.close()

    def test_connection_import_previews_and_skips_existing_connections_and_keys(self):
        import json
        from agentnik.cli import connection_menu
        from agentnik.storage import Store, load_config

        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root / "data")
            try:
                store.save_connection("Existing", {"url": "https://example.org/v1", "model": "keep"})
                fixture = root / "connection export.json"
                fixture.write_text(json.dumps({"connections": {
                    "Existing": {"url": "https://example.org/v1", "model": "replace"},
                    "New": {"url": "https://example.org/private", "model": "new", "api_key": "synthetic"},
                }}), encoding="utf-8-sig")
                before = store.config_path.read_bytes()
                with contextlib.redirect_stdout(io.StringIO()) as output, \
                        patch("builtins.input", side_effect=["", "y"]):
                    connection_menu(root / "data", "import", f'"{fixture}"')
                    self.assertEqual(store.config_path.read_bytes(), before)
                    connection_menu(root / "data", "import", str(fixture))
                current = load_config(store.config_path)["connections"]
                self.assertEqual(current["Existing"]["model"], "keep")
                self.assertEqual(current["New"]["model"], "new")
                self.assertNotIn("api_key", current["New"])
                self.assertNotIn("synthetic", output.getvalue())
                self.assertNotIn("example.org/private", output.getvalue())
            finally:
                store.db.close()

    def test_connection_import_rejects_duplicate_names_and_fields_before_approval(self):
        from agentnik.cli import import_connection_settings
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root / "data")
            try:
                path = root / "connections.json"
                for raw in (
                    '{"connections":{"A":{"url":"https://one.example"},"A":{"url":"https://two.example"}}}',
                    '{"connections":{"A":{"url":"https://one.example","url":"https://two.example"}}}',
                ):
                    path.write_text(raw, encoding="utf-8")
                    with patch("builtins.input") as prompt:
                        with self.assertRaisesRegex(ValueError, "no duplicate names or fields"):
                            import_connection_settings(store, str(path))
                        prompt.assert_not_called()
                    self.assertEqual(store.config["connections"], {})
            finally:
                store.db.close()

    def test_copy_saved_connection_does_not_copy_credentials_or_overwrite(self):
        from agentnik.cli import connection_menu
        from agentnik.storage import Store, load_config

        with TemporaryDirectory() as directory:
            data = Path(directory)
            store = Store(data)
            try:
                store.save_connection("Source", {"url": "https://example.org/v1", "model": "fixture",
                                                 "stream": False, "api_key": "synthetic"}, plaintext=True)
                before = store.config_path.read_bytes()
                with contextlib.redirect_stdout(io.StringIO()), patch("builtins.input", side_effect=["Source", "Copy"]):
                    connection_menu(data, "copy", "Source")
                    self.assertEqual(store.config_path.read_bytes(), before)
                    connection_menu(data, "copy", "Source")
                connections = load_config(store.config_path)["connections"]
                self.assertEqual(connections["Source"]["api_key"], "synthetic")
                self.assertNotIn("api_key", connections["Copy"])
                self.assertNotIn("credential_id", connections["Copy"])
                self.assertEqual(connections["Copy"]["model"], "fixture")
                self.assertFalse(connections["Copy"]["stream"])
            finally:
                store.db.close()

    def test_copy_environment_or_discovered_connection_omits_source_key(self):
        from agentnik.cli import connection_menu
        from agentnik.storage import Store, load_config

        with TemporaryDirectory() as directory:
            data = Path(directory)
            store = Store(data)
            try:
                source = {"url": "http://127.0.0.1:11434/v1", "model": "test", "api_key": "synthetic"}
                with patch("agentnik.core.environment_connections", return_value={"env:Fixture": source}), \
                        patch("builtins.input", side_effect=["Environment copy", "Discovered copy"]), \
                        contextlib.redirect_stdout(io.StringIO()):
                    connection_menu(data, "copy", "env:Fixture")
                    connection_menu(data, "copy", "local:Fixture", discovered={"local:Fixture": source})
                saved = load_config(store.config_path)["connections"]
                self.assertEqual(set(saved), {"Environment copy", "Discovered copy"})
                for entry in saved.values():
                    self.assertEqual(entry["model"], "test")
                    self.assertNotIn("api_key", entry)
                    self.assertNotIn("credential_id", entry)
                self.assertEqual(source["api_key"], "synthetic")
            finally:
                store.db.close()

    def test_manual_git_help_remains_available_without_native_git(self):
        from agentnik.code_git_commands import manual_git

        lines = []
        with patch("agentnik.code_git_commands.shutil.which", return_value=None) as find, \
                patch("agentnik.code_git_commands.subprocess.run") as run:
            manual_git(Path.cwd(), "", write=lines.append)
            find.assert_not_called()
            self.assertIn("require native Git on PATH", "\n".join(lines))
            with self.assertRaisesRegex(ValueError, "Native Git was not found on PATH"):
                manual_git(Path.cwd(), "status")
            run.assert_not_called()

    def test_terminal_tls_status_reports_saved_mode_without_writing(self):
        from agentnik.code_settings import configure_code
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            store = Store(Path(directory))
            try:
                for mode in ("relaxed", "strict"):
                    configure_code(store, ["tls", mode])
                    with patch.object(store, "flush") as flush:
                        self.assertIn(f"TLS verification: {mode}", configure_code(store, ["tls"]))
                    flush.assert_not_called()
            finally:
                store.db.close()

    def test_show_saved_connection_is_read_only_and_omits_sensitive_fields(self):
        from agentnik.cli import connection_menu
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            store = Store(Path(directory))
            try:
                store.save_connection("Fixture", {"url": "https://example.org/private-endpoint",
                                                   "model": "fixture-model", "stream": False})
                before = store.config_path.read_bytes()
                with contextlib.redirect_stdout(io.StringIO()) as output, \
                        patch("builtins.input", side_effect=AssertionError("unexpected edit prompt")):
                    connection_menu(Path(directory), "show", "Fixture")
                self.assertIn("Model: 'fixture-model'", output.getvalue())
                self.assertIn("Streaming: False", output.getvalue())
                self.assertNotIn("private-endpoint", output.getvalue())
                self.assertEqual(store.config_path.read_bytes(), before)
            finally:
                store.db.close()

    def test_machine_scope_uses_absolute_reads_without_widening_project_tools(self):
        import json
        from unittest.mock import Mock
        from agentnik import cli, core
        from agentnik.storage import Store
        from test_code_agent import call
        from test_compat_tools import chat
        from test_routing import Wire

        with TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root, data = base / "project", base / "data"
            root.mkdir()
            outside = base / "diagnostic.txt"
            outside.write_text("Outside fixture evidence", encoding="utf-8")
            store = Store(data)
            try:
                store.save_connection("Fixture", {"url": "https://example.org/v1", "model": "fixture", "stream": False})
            finally:
                store.db.close()
            composer = Mock()
            session = uuid4()
            commands = iter(["/keys", "/transcript", "/connection Fixture", "/scope machine", "/status", "Read diagnostics",
                             "/transcript",
                             "/scope project", "Continue project work",
                             "/permissions allow-all", "/scope machine", f"/resume {session}",
                             "/status", "Resumed task", "/exit"])
            labels = {}

            def open_composer(*, transcript, message):
                def prompt():
                    command = next(commands)
                    labels[command] = message()
                    return command

                composer.prompt.side_effect = prompt
                return composer
            reads = [call("machine_list_directory", {"path": str(base)}, ident="list"),
                     call("machine_inspect_path", {"path": str(outside)}, ident="metadata"),
                     call("machine_tail_file", {"path": str(outside), "lines": "1"}, ident="tail"),
                     call("machine_patch_file", {"path": str(outside), "old_text": "fixture",
                                                  "new_text": "not reviewed"}, ident="tail-only-patch"),
                     call("machine_read_file", {"path": str(outside)})]
            edit = call("machine_patch_file", {"path": str(outside), "old_text": "fixture", "new_text": "reviewed"},
                        ident="change")
            report = base / "report.txt"
            create = call("machine_create_file", {"path": str(report), "content": "Diagnostic report\n"}, ident="create")
            declined = base / "declined.txt"
            decline = call("machine_create_file", {"path": str(declined), "content": "Not approved"}, ident="decline")
            diagnostics = base / "diagnostics"
            mkdir = call("machine_create_directory", {"path": str(diagnostics)}, ident="mkdir")
            declined_directory = base / "declined-directory"
            decline_directory = call("machine_create_directory", {"path": str(declined_directory)}, ident="decline-dir")
            replies = iter([Wire(chat(calls=reads, finish="tool_calls"), False),
                            Wire(chat(calls=[edit, create, mkdir, decline, decline_directory], finish="tool_calls"), False),
                            Wire(chat("Outside fixture evidence"), False),
                            Wire(chat("Project response"), False),
                            Wire(chat(calls=[create], finish="tool_calls"), False),
                            Wire(chat("Resumed response"), False)])
            bodies = []

            def send(connection, url, body, timeout):
                bodies.append(json.loads(json.dumps(body)))
                return next(replies)

            argv = ["agentnik", "code", str(root), "--data-dir", str(data)]
            with patch("sys.argv", argv), patch("sys.stdin.isatty", return_value=True), \
                    patch.object(cli, "uuid4", return_value=session), \
                    patch("agentnik.code_composer.create_composer", side_effect=open_composer), \
                    patch("agentnik.code_composer.transcript_pager") as pager, \
                    patch("builtins.input", side_effect=["y", "y", "y", "", ""]) as approval, \
                    patch.object(core, "open_request", side_effect=send), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(), 0)
            self.assertEqual(len(bodies), 6, output.getvalue())
            self.assertIn("Machine file changes require user approval.", json.dumps(bodies[0]["messages"]))
            project_messages = json.dumps(bodies[4]["messages"])
            self.assertIn("Project scope is active. Machine file tools are unavailable.", project_messages)
            self.assertIn("builds, dependency checks, and tests may still use the normal user environment",
                          project_messages)
            self.assertIn("ask the user to enable machine scope", project_messages)
            self.assertIn("Ctrl+U/Ctrl+D scroll by half a page", output.getvalue())
            self.assertIn("No transcript for this session yet.", output.getvalue())
            pager.assert_called_once()
            self.assertIn("Created machine file", pager.call_args.args[0])
            pager.return_value.run.assert_called_once()
            self.assertEqual(approval.call_count, 5, output.getvalue())
            self.assertIn("operation: machine_patch_file", output.getvalue())
            self.assertIn("operation: machine_create_file", output.getvalue())
            self.assertIn("operation: machine_create_directory", output.getvalue())
            self.assertEqual(outside.read_text(encoding="utf-8"), "Outside reviewed evidence")
            self.assertEqual(report.read_bytes(), b"Diagnostic report\n")
            self.assertFalse(declined.exists())
            self.assertTrue(diagnostics.is_dir())
            self.assertFalse(declined_directory.exists())
            self.assertIn("Machine file creation declined by the user", json.dumps(bodies[2]["messages"]))
            self.assertIn("Machine directory creation declined by the user", json.dumps(bodies[2]["messages"]))
            self.assertIn("Permissions: require", output.getvalue())
            self.assertIn("File edits in the current scope and ordinary shell commands normally skip approval",
                          output.getvalue())
            self.assertIn("structured Git changes, and subagent file transfers still require review",
                          output.getvalue())
            self.assertIn("Scope: machine", output.getvalue())
            self.assertIn("machine_read_file", {t["function"]["name"] for t in bodies[0]["tools"]})
            self.assertNotIn("machine_read_file", {t["function"]["name"] for t in bodies[3]["tools"]})
            self.assertIn("Outside fixture evidence", json.dumps(bodies[1]["messages"]))
            listing = next(m for m in bodies[1]["messages"] if m.get("tool_call_id") == "list")
            self.assertIn({"name": "diagnostic.txt", "kind": "file"}, json.loads(listing["content"])["entries"])
            meta = next(m for m in bodies[1]["messages"] if m.get("tool_call_id") == "metadata")
            metadata = json.loads(meta["content"])
            self.assertEqual(metadata["kind"], "file")
            self.assertEqual(metadata["size_bytes"], len(b"Outside fixture evidence"))
            self.assertIsInstance(metadata["modified_unix_ns"], int)
            self.assertNotIn("text", metadata)
            tail = next(m for m in bodies[1]["messages"] if m.get("tool_call_id") == "tail")
            self.assertEqual(json.loads(tail["content"]),
                             {"text": "Outside fixture evidence", "truncated": False})
            rejected = next(m for m in bodies[1]["messages"] if m.get("tool_call_id") == "tail-only-patch")
            self.assertIn("Read the current file with machine_read_file before editing", rejected["content"])
            from agentnik.code_agent import ProjectFiles

            with self.assertRaisesRegex(ValueError, "project-relative path"):
                ProjectFiles(root).path(str(outside))
            self.assertNotIn("Outside fixture evidence", json.dumps(bodies[3]["messages"]))
            self.assertIn("Scope: project", output.getvalue())
            self.assertIn("Machine file changes require approval.", output.getvalue())
            self.assertIn("Machine file changes normally skip approval (allow-all).", output.getvalue())
            self.assertIn("Shell commands are not sandboxed in either scope.", output.getvalue())
            self.assertEqual(labels["Read diagnostics"], "code [machine]> ")
            self.assertEqual(labels["Continue project work"], "code> ")
            self.assertEqual(labels["/scope machine"], "code [allow-all]> ")
            self.assertEqual(labels[f"/resume {session}"], "code [machine, allow-all]> ")
            self.assertEqual(labels["Resumed task"], "code> ")
            self.assertFalse(any(t["function"]["name"].startswith("machine_") for t in bodies[4]["tools"]))
            self.assertIn("Unknown or unavailable tool", json.dumps(bodies[5]["messages"]))

    @unittest.skipUnless(os.name == "nt", "Windows path rules")
    def test_machine_paths_reject_windows_device_names_and_aliases(self):
        from agentnik.machine_files import absolute_machine_path

        for path in (r"C:\work\NUL.txt", r"C:\work\COM¹.log", r"C:\work\aux .txt",
                     r"C:\work\folder.\report.txt", "C:\\work\\.. \\report.txt",
                     r"C:\work\report.txt:stream", r"\\?\C:\work\report.txt"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                absolute_machine_path(path)
        for path in (r"C:\work\report.txt", r"\\server\share\report.txt"):
            self.assertEqual(absolute_machine_path(path), Path(path))

    def test_machine_mkdir_does_not_replace_a_destination_created_during_review(self):
        from agentnik.machine_files import create_machine_directory, machine_new_path

        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "diagnostics"
            parent = machine_new_path(str(target))
            target.write_bytes(b"other writer")
            with self.assertRaises(FileExistsError):
                create_machine_directory(str(target), parent, lambda: None)
            self.assertEqual(target.read_bytes(), b"other writer")
            with self.assertRaisesRegex(ValueError, "existing directory"):
                machine_new_path(str(root / "absent" / "diagnostics"))

    def test_machine_create_does_not_overwrite_a_file_created_after_preview(self):
        from agentnik.machine_files import create_machine_file, machine_create_preview

        with TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "report.txt"
            data, parent = machine_create_preview(str(path), "new report")
            path.write_bytes(b"other writer")
            with self.assertRaises(FileExistsError):
                create_machine_file(str(path), data, parent, lambda: None)
            self.assertEqual(path.read_bytes(), b"other writer")

    @unittest.skipUnless(os.open in os.supports_dir_fd and hasattr(os, "O_DIRECTORY"),
                         "Directory handles for relative file creation")
    def test_machine_creation_parent_uses_and_closes_the_verified_handle(self):
        from agentnik.machine_files import creation_parent, machine_new_path

        with TemporaryDirectory() as directory:
            target = Path(directory).resolve() / "report.txt"
            observed = machine_new_path(str(target))
            with creation_parent(target, observed, os.open) as (name, handle):
                self.assertEqual(name, "report.txt")
                self.assertIsNotNone(handle)
                parent = os.fstat(handle)
                self.assertEqual((parent.st_dev, parent.st_ino), observed)
            with self.assertRaises(OSError):
                os.fstat(handle)

    def test_machine_creation_stops_if_the_reviewed_parent_is_replaced(self):
        from agentnik.machine_files import create_machine_directory, create_machine_file, machine_create_preview, machine_new_path

        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            parent = root / "parent"
            parent.mkdir()
            child_dir = str(parent / "new-dir")
            child_file = str(parent / "new.txt")
            directory_observed = machine_new_path(child_dir)
            data, file_observed = machine_create_preview(child_file, "new")
            parent.rename(root / "original")
            parent.mkdir()
            with self.assertRaisesRegex(ValueError, "directory changed during review"):
                create_machine_directory(child_dir, directory_observed, lambda: None)
            with self.assertRaisesRegex(ValueError, "directory changed during review"):
                create_machine_file(child_file, data, file_observed, lambda: None)
            self.assertEqual(list(parent.iterdir()), [])

    def test_machine_patch_reviews_unterminated_lines_and_rejects_overlapping_matches(self):
        from agentnik.machine_files import machine_patch_preview, open_machine_text

        with TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "settings.txt"
            path.write_bytes(b"aaa")
            with open_machine_text(str(path)) as (_, _, observed):
                pass
            with self.assertRaisesRegex(ValueError, "must occur once"):
                machine_patch_preview(str(path), observed, "aa", "x")
            replacement, diff = machine_patch_preview(str(path), observed, "aaa", "x")
            self.assertEqual(replacement, "x")
            self.assertEqual(diff.splitlines()[-4:],
                             ["-aaa", r"\ No newline at end of file",
                              "+x", r"\ No newline at end of file"])

    def test_machine_patch_rejects_a_change_after_preview(self):
        from agentnik.machine_files import apply_machine_patch, machine_patch_preview, open_machine_text

        with TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "diagnostic.txt"
            path.write_bytes(b"one\r\ntwo\r\n")
            with open_machine_text(str(path)) as (_, _, observed):
                pass
            replacement, _ = machine_patch_preview(str(path), observed, "two", "three")
            self.assertEqual(replacement, "one\r\nthree\r\n")
            path.write_bytes(b"concurrent edit")
            with self.assertRaisesRegex(ValueError, "changed after it was read"):
                apply_machine_patch(str(path), observed, replacement, lambda: None)
            self.assertEqual(path.read_bytes(), b"concurrent edit")

    @unittest.skipUnless(os.name == "posix", "POSIX symlinks and modes")
    def test_machine_metadata_reports_dangling_link_and_binary_file_without_reading(self):
        from agentnik.machine_files import inspect_machine_path

        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            link = root / "broken"
            link.symlink_to(root / "missing")
            binary = root / "payload.bin"
            binary.write_bytes(b"\x00\xff")
            binary.chmod(0o640)
            with patch.object(Path, "open", side_effect=AssertionError("unexpected content read")):
                self.assertEqual(inspect_machine_path(str(link))["kind"], "link")
                details = inspect_machine_path(str(binary))
                self.assertEqual(details["kind"], "file")
                self.assertEqual(details["size_bytes"], 2)
                self.assertEqual(details["mode_octal"], "0640")

    def test_machine_tail_reads_recent_lines_from_an_oversized_log(self):
        from agentnik.code_limits import FULL_TEXT_BYTES
        from agentnik.machine_files import tail_machine_text

        with TemporaryDirectory() as directory:
            log = Path(directory).resolve() / "service.log"
            log.write_bytes(("é" * FULL_TEXT_BYTES).encode("utf-8") + b"\nold\r\nnew\r\nlatest")
            self.assertEqual(tail_machine_text(str(log), "2"),
                             {"text": "new\r\nlatest", "truncated": True})
            log.write_bytes(b"one\ntwo\n")
            self.assertEqual(tail_machine_text(str(log), "3"),
                             {"text": "one\ntwo\n", "truncated": False})
            with self.assertRaisesRegex(ValueError, "between 1 and 200"):
                tail_machine_text(str(log), "201")
            with self.assertRaisesRegex(ValueError, "absolute path"):
                tail_machine_text("service.log", "2")

    def test_machine_directory_listing_is_bounded_and_rejects_relative_paths(self):
        from agentnik.machine_files import list_machine_directory

        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for index in range(101):
                (root / f"fixture-{index}").touch()
            result = list_machine_directory(str(root))
            self.assertEqual(len(result["entries"]), 100)
            self.assertTrue(result["truncated"])
            with self.assertRaisesRegex(ValueError, "absolute path"):
                list_machine_directory(".")

    def test_terminal_resolves_tilde_data_directory_for_session_and_lock(self):
        from agentnik import cli

        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            argv = ["agentnik", "code", str(root), "--data-dir", "~/agentnik-fixture"]
            with patch.dict("os.environ", {"HOME": str(root), "USERPROFILE": str(root)}), \
                    patch("sys.argv", argv), patch("sys.stdin.isatty", return_value=True), \
                    patch("agentnik.cli.terminal_session", return_value=0) as session:
                self.assertEqual(cli.main(), 0)
            options, _, lease, _ = session.call_args.args
            self.assertEqual(options.data_dir, root / "agentnik-fixture")
            self.assertEqual(lease.directory.parent, options.data_dir)

    def test_version_does_not_open_a_terminal_or_data_store(self):
        from agentnik import __version__, cli

        with TemporaryDirectory() as directory:
            data = Path(directory) / "unused"
            with patch("sys.argv", ["agentnik", "code", "--version", "--data-dir", str(data)]), \
                    patch("sys.stdin.isatty", return_value=False), \
                    contextlib.redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit) as stopped:
                cli.main()
            self.assertEqual(stopped.exception.code, 0)
            self.assertEqual(output.getvalue().strip(), f"Agentnik Code {__version__}")
            self.assertFalse(data.exists())

    def test_terminal_rejects_a_file_as_the_data_directory(self):
        from agentnik import cli

        with TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "not-a-directory"
            data.write_text("Keep this")
            argv = ["agentnik", "code", str(root), "--data-dir", str(data)]
            with patch("sys.argv", argv), patch("sys.stdin.isatty", return_value=True), \
                    patch("agentnik.cli.terminal_session") as session, \
                    contextlib.redirect_stderr(io.StringIO()) as output, self.assertRaises(SystemExit) as stopped:
                cli.main()
            self.assertEqual(stopped.exception.code, 2)
            self.assertIn("application data path must be a directory", output.getvalue())
            self.assertEqual(data.read_text(), "Keep this")
            session.assert_not_called()

    def test_unlimited_alias_respects_bounded_limits(self):
        from agentnik.code_settings import configure_code
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                configure_code(store, ["goal", "steps", "unlimited"])
                self.assertEqual(store.config["settings"]["coding_goal_limits"]["steps"], 0)
                configure_code(store, ["limits", "requests", "unlimited"])
                with patch.object(store, "flush") as flush:
                    self.assertIn("goal steps: unlimited", configure_code(store, ["goal"]))
                    self.assertIn("requests: unlimited", configure_code(store, ["limits"]))
                    self.assertIn("model_seconds: 300", configure_code(store, ["limits"]))
                    flush.assert_not_called()
                self.assertIn("requests: unlimited", configure_code(store, ["limits", "requests"]))
                self.assertIn("default unlimited", configure_code(store, ["goal", "steps"]))
                with self.assertRaisesRegex(ValueError, "between 1 and 256, or 0 for unlimited"):
                    configure_code(store, ["limits", "requests", "257"])
                self.assertIn("requests: unlimited", configure_code(store, ["limits", "requests"]))
                with self.assertRaisesRegex(ValueError, "cannot be unlimited"):
                    configure_code(store, ["limits", "model_seconds", "unlimited"])
            finally:
                store.db.close()

    def test_headless_pdf_extracts_text_and_rejects_encryption(self):
        from importlib.util import find_spec
        from agentnik.document_reader import read_document

        if find_spec("pypdf") is None:
            self.skipTest("Terminal PDF extra is not installed")
        writer = pdf_fixture()
        data = io.BytesIO()
        writer.write(data)
        self.assertIn("[Page 1]\nHeadless PDF fixture", read_document("fixture.pdf", data.getvalue(), headless=True))
        writer.encrypt("fixture-password")
        data = io.BytesIO()
        writer.write(data)
        with self.assertRaisesRegex(ValueError, "Encrypted PDFs"):
            read_document("fixture.pdf", data.getvalue(), headless=True)

    def test_oauth_renewal_marks_uncertainty_and_never_retries_an_unfinished_exchange(self):
        from contextlib import nullcontext
        from email.message import Message
        import json
        from unittest.mock import Mock
        from agentnik.mcp_oauth_terminal import renew_mcp_credential

        server = {"url": "https://example.org/mcp", "credential_id": "fixture"}
        record = {"version": 1, "resource_url": server["url"], "issuer": "https://auth.example.org",
                  "token_endpoint": "https://auth.example.org/token", "client_id": "client",
                  "access_token": "old", "refresh_token": "old-refresh", "expires_at": 1, "refresh_pending": False}
        stored = [record]

        def write(service, ident, value):
            stored[0] = json.loads(value)

        def response(request, timeout):
            self.assertTrue(stored[0]["refresh_pending"])
            self.assertEqual(request.full_url, record["token_endpoint"])
            reply = io.BytesIO(b'{"token_type":"Bearer","access_token":"new","expires_in":3600}')
            reply.status = 200
            reply.headers = Message()
            reply.headers["Content-Type"] = "application/json"
            return reply

        with patch("agentnik.mcp_oauth_terminal.oauth_refresh_lease", side_effect=lambda _: nullcontext()), \
                patch("keyring.get_password", side_effect=lambda *_: json.dumps(stored[0])), \
                patch("keyring.set_password", side_effect=write), \
                patch("agentnik.mcp_oauth_terminal.build_opener") as opener:
            renew_mcp_credential(server, lambda _: False)
            opener.assert_not_called()
            opener.return_value = Mock(open=response)
            self.assertEqual(renew_mcp_credential(server, lambda _: True), "Renewed MCP OAuth sign-in.")
            self.assertEqual(stored[0]["access_token"], "new")
            self.assertFalse(stored[0]["refresh_pending"])
            stored[0] = record
            opener.return_value = Mock(open=Mock(side_effect=OSError("offline")))
            with self.assertRaisesRegex(ValueError, "not retried"):
                renew_mcp_credential(server, lambda _: True)
            with self.assertRaisesRegex(ValueError, "cannot be renewed"):
                renew_mcp_credential(server, lambda _: True)
            opener.return_value.open.assert_called_once()

    def test_terminal_mcp_reuses_only_ready_oauth_records_for_the_selected_server(self):
        import json
        from agentnik.code_terminal import terminal_mcp_bridges

        profile = {"name": "OAuth", "transport": "http", "url": "https://example.org/mcp",
                   "credential_id": "fixture", "enabled": True, "auth_type": "oauth"}
        config = {"settings": {}, "mcp_servers": [profile]}
        record = {"version": 1, "resource_url": profile["url"], "issuer": "https://auth.example.org",
                  "token_endpoint": "https://auth.example.org/token", "client_id": "client",
                  "access_token": "access-fixture", "refresh_token": "refresh-fixture",
                  "expires_at": None, "refresh_pending": False}
        with patch("keyring.get_password", return_value=json.dumps(record)) as get:
            bridge, = terminal_mcp_bridges(config, [profile])
            self.assertEqual(bridge.token, "access-fixture")
            get.assert_called_once_with("Agentnik", "fixture")
        with patch("keyring.get_password", return_value=json.dumps(dict(record, refresh_pending=True))):
            with self.assertRaisesRegex(ValueError, "needs renewal"):
                terminal_mcp_bridges(config, [profile])
        with patch("keyring.get_password", return_value=json.dumps(dict(record, resource_url="https://other.example.org/mcp"))):
            with self.assertRaisesRegex(ValueError, "sign-in is unavailable"):
                terminal_mcp_bridges(config, [profile])

    def test_terminal_mcp_keeps_selection_order_and_rejects_stale_profiles(self):
        from agentnik.code_terminal import terminal_mcp_bridges

        local = {"name": "Local", "command": "fixture", "args": [], "enabled": True}
        https = {"name": "HTTPS", "transport": "http", "url": "https://example.org/mcp",
                 "credential_id": "", "enabled": True}
        config = {"settings": {}, "mcp_servers": [local, https]}
        bridges = terminal_mcp_bridges(config, [https, local])
        self.assertEqual([bridge.server["name"] for bridge in bridges], ["HTTPS", "Local"])
        for bridge in bridges:
            bridge.close_from_worker()
        config["mcp_servers"] = [local, dict(https, enabled=False)]
        with self.assertRaisesRegex(ValueError, "changed or is unavailable"):
            terminal_mcp_bridges(config, [https, local])

    def test_stdio_probe_handles_silent_modern_and_delayed_legacy_servers(self):
        import sys
        from textwrap import dedent
        from agentnik.mcp_terminal import TerminalMCPBridge
        from agentnik.tools import Runtime

        fixture = dedent("""
            import json, sys
            legacy = sys.argv[1] == "legacy"
            def send(ident, **payload):
                print(json.dumps(dict(jsonrpc="2.0", id=ident, **payload)), flush=True)
            for line in sys.stdin:
                message = json.loads(line)
                method = message["method"]
                if method == "server/discover":
                    if legacy:
                        send(1, result={"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                                        "serverInfo": {"name": "fixture", "version": "1"}})
                        send(0, error={"code": -32601, "message": "Method not found"})
                    else:
                        send(0, result={"supportedVersions": ["2026-07-28"], "capabilities": {"tools": {}}})
                elif method == "tools/list":
                    send(message["id"], result={"tools": [{"name": "fixture", "inputSchema": {"type": "object"}}]})
        """)
        for mode, protocol in (("modern", "2026-07-28"), ("legacy", "2025-11-25")):
            with self.subTest(mode=mode), patch("agentnik.mcp_terminal.STARTUP_PROBE_SECONDS", 0.05):
                bridge = TerminalMCPBridge({"name": "Fixture", "command": sys.executable,
                                            "args": ["-u", "-c", fixture, mode]})
                try:
                    catalog = bridge.request("discover", {}, Runtime())
                    self.assertEqual(catalog.get("protocol"), protocol, catalog)
                    self.assertEqual(catalog["tool_details"][0]["name"], "fixture")
                finally:
                    bridge.close_from_worker()

    def test_local_mcp_negotiates_2026_after_legacy_envelope_rejection(self):
        import sys
        from textwrap import dedent
        from agentnik.mcp_terminal import TerminalMCPBridge
        from agentnik.tools import Runtime

        fixture = dedent("""
            import json, sys
            for line in sys.stdin:
                message = json.loads(line)
                method = message["method"]
                response = {"jsonrpc": "2.0", "id": message["id"]}
                if method == "initialize":
                    response["error"] = {"code": -32601, "message": "Use discovery"}
                else:
                    assert message["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"
                    if method == "server/discover":
                        result = {"supportedVersions": ["2026-07-28"], "capabilities": {"tools": {}}}
                    elif method == "tools/list":
                        result = {"tools": [{"name": "fixture", "inputSchema": {"type": "object"}}]}
                    else:
                        result = {"resultType": "input_required", "private": "not exposed"}
                    response["result"] = result
                print(json.dumps(response), flush=True)
        """)
        bridge = TerminalMCPBridge({"name": "Modern", "command": sys.executable, "args": ["-u", "-c", fixture]})
        try:
            catalog = bridge.request("discover", {}, Runtime())
            self.assertEqual(catalog["protocol"], "2026-07-28", catalog)
            outcome = bridge.request("call", {"tool": catalog["tool_details"][0], "arguments": {}}, Runtime())
            self.assertIn("not continued", outcome["error"])
            self.assertNotIn("not exposed", str(outcome))
        finally:
            bridge.close_from_worker()

    def test_remote_mcp_carries_session_headers_and_handles_sse_without_qt(self):
        from email.message import Message
        import json
        from unittest.mock import Mock
        from agentnik.mcp_terminal_http import TerminalHTTPMCPBridge
        from agentnik.tools import Runtime

        class Reply(io.BytesIO):
            def __init__(self, payload=b"", status=200, content_type="application/json", session=None):
                super().__init__(payload)
                self.status = status
                self.headers = Message()
                self.headers["Content-Type"] = content_type
                if session:
                    self.headers["MCP-Session-Id"] = session

        requests = []

        def open_request(request, timeout):
            headers = {key.lower(): value for key, value in request.header_items()}
            self.assertEqual(headers["authorization"], "Bearer fixture-key")
            body = json.loads(request.data) if request.data else None
            requests.append((request.get_method(), body, headers))
            if body is None:
                return Reply(status=204)
            method = body["method"]
            if method == "notifications/initialized":
                return Reply(status=202)
            if method == "server/discover":
                return Reply(json.dumps({"jsonrpc": "2.0", "id": 0,
                                        "error": {"code": -32601, "message": "Method not found"}}).encode())
            if method == "initialize":
                result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "fixture", "version": "1"}}
            elif method == "tools/list":
                result = {"tools": [{"name": "hello", "inputSchema": {"type": "object"}}]}
            else:
                result = {"content": [{"type": "text", "text": "Hello over HTTPS"}]}
            envelope = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
            if method == "tools/call":
                return Reply(b"data: " + envelope + b"\n\n", content_type="text/event-stream")
            return Reply(envelope, session="fixture-session" if method == "initialize" else None)

        bridge = TerminalHTTPMCPBridge({"name": "Remote", "url": "https://example.org/mcp"}, "fixture-key")
        with patch("agentnik.mcp_terminal_http.build_opener", return_value=Mock(open=open_request)):
            try:
                catalog = bridge.request("discover", {}, Runtime())
                answer = bridge.request("call", {"tool": catalog["tool_details"][0], "arguments": {}}, Runtime())
                self.assertEqual(answer["call_result"]["content"][0]["text"], "Hello over HTTPS")
            finally:
                bridge.close_from_worker()
        self.assertEqual(requests[-1][0], "DELETE")
        self.assertEqual(requests[0][1]["method"], "server/discover")
        self.assertNotIn("mcp-session-id", requests[1][2])
        for _, _, headers in requests[2:]:
            self.assertEqual(headers["mcp-session-id"], "fixture-session")
            self.assertEqual(headers["mcp-protocol-version"], "2025-06-18")

    def test_remote_mcp_negotiates_2026_and_does_not_fallback_on_auth_errors(self):
        from email.message import Message
        import json
        from urllib.error import HTTPError
        from agentnik.mcp_terminal_http import TerminalHTTPMCPBridge
        from agentnik.tools import Runtime

        profile = {"name": "Remote", "url": "https://example.org/mcp"}
        bridge = TerminalHTTPMCPBridge(profile)
        requests = []

        def reply(method, message, timeout, headers):
            self.assertEqual(method, "POST")
            requests.append(message["method"])
            self.assertEqual(headers["MCP-Protocol-Version"], "2026-07-28")
            self.assertEqual(headers["Mcp-Method"], message["method"])
            if message["method"] == "server/discover":
                result = {"supportedVersions": ["2026-07-28"], "capabilities": {"tools": {}}}
            elif message["method"] == "tools/list":
                result = {"tools": [{"name": "greet", "inputSchema": {
                    "type": "object", "properties": {"region": {"type": "string", "x-mcp-header": "region"}},
                }}]}
            else:
                self.assertEqual(headers["Mcp-Name"], "greet")
                self.assertEqual(headers["Mcp-Param-region"], "west")
                result = {"resultType": "complete", "content": [{"type": "text", "text": "Modern hello"}]}
            response = io.BytesIO(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}).encode())
            response.status = 200
            response.headers = Message()
            response.headers["Content-Type"] = "application/json"
            return response

        with patch.object(bridge, "_open", side_effect=reply):
            try:
                catalog = bridge.request("discover", {}, Runtime())
                result = bridge.request("call", {"tool": catalog["tool_details"][0],
                                                  "arguments": {"region": "west"}}, Runtime())
            finally:
                bridge.close_from_worker()
        self.assertEqual(result["call_result"]["content"][0]["text"], "Modern hello")
        self.assertEqual(requests, ["server/discover", "tools/list", "tools/list", "tools/call"])
        bridge = TerminalHTTPMCPBridge(profile)
        with patch.object(bridge, "_open", side_effect=HTTPError(profile["url"], 401, "", Message(), None)) as open_request:
            self.assertIn("HTTP 401", bridge.request("discover", {}, Runtime())["error"])
            open_request.assert_called_once()

    def test_headless_local_mcp_checks_approvals_for_tools_and_resources(self):
        import sys
        from textwrap import dedent
        from unittest.mock import Mock
        from agentnik import cli, core
        from agentnik.storage import Store
        from test_code_agent import call
        from test_compat_tools import chat
        from test_routing import Wire

        server_code = dedent("""
            import json, sys
            for line in sys.stdin:
                message = json.loads(line)
                method = message["method"]
                if method == "initialize":
                    result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}, "resources": {}, "prompts": {}, "completions": {}},
                              "serverInfo": {"name": "fixture", "version": "1"}}
                elif method == "tools/list":
                    result = {"tools": [{"name": "hello", "description": "Return a greeting",
                                         "inputSchema": {"type": "object"}}]}
                elif method == "tools/call":
                    result = {"content": [{"type": "text", "text": "Hello from the local fixture"}]}
                elif method == "resources/list":
                    result = {"resources": [{"uri": "fixture://notes", "name": "Notes"}]}
                elif method == "resources/read":
                    uri = message["params"]["uri"]
                    result = {"contents": [{"uri": uri, "text": "Fixture resource content for " + uri}]}
                elif method == "resources/templates/list":
                    result = {"resourceTemplates": [{"uriTemplate": "fixture://items/{id}", "name": "Item"}]}
                elif method == "prompts/list":
                    result = {"prompts": [{"name": "greeting", "arguments": [{"name": "name"}]}]}
                elif method == "completion/complete":
                    assert message["params"]["argument"] == {"name": "name", "value": "fi"}
                    result = {"completion": {"values": ["fixture-suggestion"]}}
                elif method == "prompts/get":
                    result = {"messages": [{"role": "user", "content": {"type": "text", "text": "Fixture prompt content"}}]}
                else:
                    continue
                print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
        """)
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            store = Store(root / "data")
            try:
                store.save_connection("Fixture", {"url": "https://gateway.example/v1", "model": "test",
                                                  "protocol": "chat", "stream": False})
                store.config["mcp_servers"] = [{"name": "Local Fixture", "command": sys.executable,
                                                 "args": ["-u", "-c", server_code], "enabled": True}]
                store.flush()
            finally:
                store.db.close()
            composer = Mock()
            composer.prompt.side_effect = ["/connection Fixture", "/mcp use Local Fixture", "Run greeting", "/exit"]
            output = io.StringIO()
            with patch("sys.argv", ["agentnik", "code", str(root), "--data-dir", str(root / "data")]), \
                    patch("sys.stdin.isatty", return_value=True), \
                    patch("agentnik.code_composer.create_composer", return_value=composer), \
                    patch("builtins.input", side_effect=["y"] * 9) as approval, \
                    patch.object(core, "open_request", side_effect=[
                        Wire(chat(calls=[call("mcp_discover", {})], finish="tool_calls"), False),
                        Wire(chat(calls=[call("mcp_call", {"tool": "hello", "arguments": "{}"})],
                                  finish="tool_calls"), False),
                        Wire(chat(calls=[call("mcp_list_resources", {})], finish="tool_calls"), False),
                        Wire(chat(calls=[call("mcp_read_resource", {"uri": "fixture://notes"})],
                                  finish="tool_calls"), False),
                        Wire(chat(calls=[call("mcp_list_resource_templates", {})], finish="tool_calls"), False),
                        Wire(chat(calls=[call("mcp_read_resource_template", {
                            "template": "fixture://items/{id}", "variables": '{"id":"17"}',
                        })], finish="tool_calls"), False),
                        Wire(chat(calls=[call("mcp_list_prompts", {})], finish="tool_calls"), False),
                        Wire(chat(calls=[call("mcp_complete_argument", {
                            "request": '{"kind":"prompt","target":"greeting","argument":"name","value":"fi","context":{}}',
                        })], finish="tool_calls"), False),
                        Wire(chat(calls=[call("mcp_get_prompt", {"name": "greeting", "arguments": "{}"})],
                                  finish="tool_calls"), False),
                        Wire(chat("Done"), False),
                    ]) as transport, contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(), 0)
            self.assertEqual(approval.call_count, 9, output.getvalue())
            self.assertEqual(transport.call_count, 10, output.getvalue())
            self.assertIn("Hello from the local fixture", str(transport.call_args_list[2].args[2]))
            self.assertIn("Fixture resource content", str(transport.call_args_list[4].args[2]))
            self.assertIn("Fixture resource content for fixture://items/17", str(transport.call_args_list[6].args[2]))
            self.assertIn("fixture-suggestion", str(transport.call_args_list[8].args[2]))
            self.assertIn("Fixture prompt content", str(transport.call_args_list[9].args[2]))

    def test_only_lease_owner_can_recover_an_interrupted_goal(self):
        from agentnik.code_history import CodeHistory, goal_continuation
        from agentnik.code_lease import SessionLease
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            data = root / "data"
            store = Store(data)
            try:
                history = CodeHistory(store, root)
                session = str(uuid4())
                history.start("fixture", {"model": "test"}, "Finish project", session, goal=True)
                with SessionLease(data) as lease, SessionLease(data) as other:
                    record = history.list(session)[0]
                    history.checkpoint_goal(record, {"kind": "goal_status", "status": "active",
                                                     "detail": "Draft was created."})
                    history.checkpoint_goal(record, {"kind": "goal_progress", "steps": 2, "seconds": 3.0})
                    history.checkpoint(record, {"kind": "project_change", "label": "edit", "path": "draft.md"})
                    record = history.list(session)[0]
                    history.recover_interrupted(record, lease)
                    self.assertEqual(record["code_state"], "running")
                    lease.select(session)
                    unrelated = str(uuid4())
                    other.select(unrelated)
                    with self.assertRaisesRegex(ValueError, "already open"):
                        history.prepare_resume(session, other)
                    self.assertEqual(other.session_id, unrelated)
                    self.assertEqual(history.list(session)[0]["code_state"], "running")
                    lease.close()
                    ident, snapshot = history.prepare_resume(session, other)
                    self.assertEqual(ident, session)
                    self.assertEqual(other.session_id, session)
                    self.assertEqual(snapshot.prompt_history, ("Finish project",))
                    saved = snapshot.record
                    self.assertEqual(history.list(session)[0]["code_state"], "interrupted")
                    self.assertEqual(saved["coding_goal"]["status"], "interrupted")
                    self.assertEqual(goal_continuation(saved)["task"], "Finish project")
                    self.assertIn("Draft was created.", goal_continuation(saved)["evidence"])
                    self.assertIn("Recorded goal steps: 2.", goal_continuation(saved)["evidence"])
                    self.assertIn("Applied project edit: draft.md", goal_continuation(saved)["evidence"])
            finally:
                store.db.close()

    def test_session_lease_rejects_duplicate_attachment_and_releases_on_close(self):
        from agentnik.code_lease import SessionLease

        with TemporaryDirectory() as directory, SessionLease(directory) as left, SessionLease(directory) as right:
            first, second = str(uuid4()), str(uuid4())
            left.select(first)
            right.select(second)
            with self.assertRaisesRegex(ValueError, "already open"):
                right.select(first)
            self.assertEqual(right.session_id, second)
            left.close()
            right.select(first)
            self.assertEqual(right.session_id, first)

    def test_two_open_sessions_keep_separate_goal_and_prompt_history(self):
        from agentnik.code_history import CodeHistory
        from agentnik.code_lease import SessionLease
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root, data = base / "project", base / "data"
            root.mkdir()
            first, second = str(uuid4()), str(uuid4())
            left_store, right_store = Store(data), Store(data)
            try:
                with SessionLease(data) as left, SessionLease(data) as right:
                    left.select(first)
                    right.select(second)
                    left_history = CodeHistory(left_store, root)
                    right_history = CodeHistory(right_store, root)
                    first_record, first_task = left_history.start(
                        "Fixture", {"model": "test"}, "Review slides", first, goal=True)
                    second_record, second_task = right_history.start(
                        "Fixture", {"model": "test"}, "Update documentation", second, goal=True)
                    right_history.finish(second_record, second_task, {"status": "completed", "text": "Docs done"})
                    left_history.finish(first_record, first_task, {"status": "cancelled", "text": "Slides paused"})
                    for history in (left_history, right_history):
                        self.assertEqual(set(history.sessions()), {first, second})
                        for session, task, state in ((first, "Review slides", "cancelled"),
                                                     (second, "Update documentation", "completed")):
                            from agentnik.sessions import validate_session
                            with patch("agentnik.storage.validate_session", wraps=validate_session) as validate:
                                saved, = history.list(session)
                            validate.assert_called_once()
                            self.assertEqual(saved["coding_goal"]["objective"], task)
                            self.assertEqual(saved["code_state"], state)
                            self.assertEqual([item["text"] for item in saved["code_activity"]
                                              if item["kind"] == "prompt"], [task])
                    newer, prompt = left_history.start("Fixture", {"model": "test"}, "Follow-up", first)
                    left_history.finish(newer, prompt, {"status": "completed", "text": "Done"})
                    summaries = right_history.session_summaries()
                    self.assertEqual(list(summaries)[0], first)
                    turn, goal_status = summaries[first]
                    self.assertEqual(turn["code_state"], "completed")
                    self.assertNotIn("coding_goal", turn)
                    self.assertEqual(goal_status, "cancelled")
                    self.assertEqual(summaries[second][1], "completed")
            finally:
                left_store.db.close()
                right_store.db.close()

    def test_launch_cannot_resume_a_session_from_another_project(self):
        from agentnik import cli, core
        from agentnik.code_history import CodeHistory
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            first, second, data = base / "first", base / "second", base / "data"
            first.mkdir()
            second.mkdir()
            session = str(uuid4())
            store = Store(data)
            try:
                history = CodeHistory(store, first)
                record, task = history.start("Fixture", {"model": "test"}, "Other project's prompt", session)
                history.finish(record, task, {"status": "completed", "text": "Done"})
            finally:
                store.db.close()

            argv = ["agentnik", "code", str(second), "--data-dir", str(data), "--resume", session]
            with patch("sys.argv", argv), patch("sys.stdin.isatty", return_value=True), \
                    patch("agentnik.code_composer.create_composer"), \
                    patch.object(CodeHistory, "sessions", side_effect=AssertionError("unexpected session scan")), \
                    patch.object(core, "open_request") as request, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(), 1)
            request.assert_not_called()
            self.assertIn("No saved session with that ID in this project", output.getvalue())
            self.assertNotIn("Other project's prompt", output.getvalue())

    def test_busy_resume_preserves_the_current_terminal_session(self):
        from unittest.mock import Mock
        from agentnik import cli, core
        from agentnik.code_history import CodeHistory
        from agentnik.code_lease import SessionLease
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root, data = base / "project", base / "data"
            root.mkdir()
            current, busy = str(uuid4()), str(uuid4())
            store = Store(data)
            try:
                history = CodeHistory(store, root)
                connection = {"url": "https://example.org/v1", "model": "fixture"}
                for ident, prompt in ((current, "Current task"), (busy, "Other terminal task")):
                    record, _ = history.start("Fixture", connection, prompt, ident, goal=True)
                    history.finish(record, prompt, {"status": "completed", "text": "Done"})
                    if ident == current:
                        record["coding_models"] = {"heavy": record["coding_models"]["model"]}
                        store.save(record)
                        history.checkpoint(record, {"kind": "plan", "plan": {"explanation": "", "steps": [
                            {"step": "Current checklist", "status": "pending"},
                        ]}})
                composer = Mock()
                composer.prompt.side_effect = [f"/resume {busy}", "/status", "/plan", "/goal", "/new", "/plan", "/goal", "/exit"]
                argv = ["agentnik", "code", str(root), "--data-dir", str(data), "--resume", current]
                with SessionLease(data) as other, patch("sys.argv", argv), \
                        patch("sys.stdin.isatty", return_value=True), \
                        patch("agentnik.code_composer.create_composer", return_value=composer), \
                        patch.object(core, "open_request") as transport, \
                        contextlib.redirect_stdout(io.StringIO()) as output, \
                        contextlib.redirect_stderr(io.StringIO()) as errors:
                    other.select(busy)
                    self.assertEqual(cli.main(), 0)
                transport.assert_not_called()
                self.assertIn("already open in another terminal", errors.getvalue())
                self.assertIn(f"Session: {current}", output.getvalue())
                self.assertIn("Connection: 'Fixture' · Model: 'fixture'", output.getvalue())
                self.assertEqual(output.getvalue().count("[pending] Current checklist"), 2)
                self.assertIn("No saved plan for this session.", output.getvalue())
                self.assertIn("Most recent saved goal (completed):\nCurrent task", output.getvalue())
                self.assertIn("No saved goal for this session.", output.getvalue())
                self.assertNotIn("Other terminal task", output.getvalue())
                composer.history.append_string.assert_called_once_with("Current task")
            finally:
                store.db.close()

    def test_model_picker_filters_catalog_and_does_not_echo_reflected_credentials(self):
        from agentnik.code_terminal import choose_catalog_model, load_run_settings

        discovered = {"local:fixture": {"url": "http://localhost:11434/v1", "api_key": "test-secret"}}
        with TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()) as output, \
                patch("agentnik.core.models", return_value=[
                    "a-model", "b-model", "a-test-secret", "a-\x1b[2J",
                ]) as catalog, patch("builtins.input", return_value="1"):
            self.assertEqual(choose_catalog_model(directory, "local:fixture", "a-", discovered), "a-model")
            connection, *_ = load_run_settings(directory, "local:fixture", "a-model", discovered=discovered)
            self.assertEqual(connection["model"], "a-model")
        catalog.assert_called_once()
        self.assertNotIn("test-secret", output.getvalue())
        self.assertNotIn("b-model", output.getvalue())
        self.assertNotIn("\x1b", output.getvalue())

    def test_project_diff_distinguishes_worktree_from_index(self):
        from dulwich import porcelain
        from agentnik.code_terminal import project_diff

        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / "some note.txt"
            with porcelain.init(root) as repo:
                path.write_text("base\n")
                porcelain.add(repo, [path.name])
                porcelain.commit(repo, message=b" fixture", author=b"Test <test@example.org>",
                                 committer=b"Test <test@example.org>", no_verify=True, sign=False)
                path.write_text("staged\n")
                porcelain.add(repo, [path.name])
                path.write_text("working\n")
                self.assertIn("+working", project_diff(root, path.name))
                self.assertIn("+staged", project_diff(root, "--staged " + path.name))
                self.assertIn("Unstaged", project_diff(root, ""))

    def test_mcp_signin_persists_only_the_credential_reference(self):
        from agentnik.code_settings import configure_code
        from agentnik.storage import Store, load_config

        with TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                with patch("builtins.input", side_effect=["Fixture Server", "https://example.org/mcp"]):
                    configure_code(store, ["mcp", "add-https"])
                record = {"access_token": "fixture-secret-token"}
                with patch("builtins.input", side_effect=["fixture-client", "read"]), \
                        patch("agentnik.mcp_oauth_signin.sign_in", return_value=record) as signin, \
                        patch("agentnik.mcp_oauth_record.write_record") as save:
                    configure_code(store, ["mcp", "signin", "Fixture", "Server"])
                profile = load_config(store.config_path)["mcp_servers"][0]
                self.assertEqual(profile["auth_type"], "oauth")
                self.assertIn("OAuth configured", configure_code(store, ["mcp"]))
                self.assertFalse(profile["enabled"])
                save.assert_called_once_with(profile["credential_id"], record)
                self.assertEqual(signin.call_args.args[:3], ("https://example.org/mcp", "fixture-client", "read"))
                self.assertNotIn("fixture-secret-token", store.config_path.read_text())
            finally:
                store.db.close()

    def test_mcp_preferences_and_disabled_https_server_are_saved_without_contact(self):
        from agentnik.code_settings import configure_code
        from agentnik.storage import Store, load_config

        with TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                with patch("builtins.input", side_effect=["Fixture Server", "https://example.org/mcp"]):
                    configure_code(store, ["mcp", "add-https"])
                self.assertFalse(load_config(store.config_path)["mcp_servers"][0]["enabled"])
                with patch("agentnik.code_settings.getpass", return_value="fixture-token"), \
                        patch("keyring.set_password") as save:
                    configure_code(store, ["mcp", "token", "Fixture", "Server"])
                credential = load_config(store.config_path)["mcp_servers"][0]["credential_id"]
                save.assert_called_once_with("Agentnik", credential, "fixture-token")
                self.assertNotIn("fixture-token", store.config_path.read_text())
                with patch("keyring.get_password") as read_secret:
                    summary = configure_code(store, ["mcp"])
                    read_secret.assert_not_called()
                self.assertIn("bearer token configured", summary)
                self.assertNotIn(credential, summary)
                with patch("builtins.input", side_effect=["", "https://other.example.org/mcp"]):
                    with self.assertRaisesRegex(ValueError, "Clear the saved credential"):
                        configure_code(store, ["mcp", "edit-https", "Fixture", "Server"])
                with patch("builtins.input", side_effect=["Renamed Server", ""]):
                    configure_code(store, ["mcp", "edit-https", "Fixture", "Server"])
                self.assertEqual(load_config(store.config_path)["mcp_servers"][0]["credential_id"], credential)
                with patch("builtins.input", side_effect=["Fixture Server", ""]):
                    configure_code(store, ["mcp", "edit-https", "Renamed", "Server"])
                with patch("agentnik.code_settings.getpass", return_value=""), \
                        patch("builtins.input", return_value="y"), patch("keyring.delete_password") as remove:
                    configure_code(store, ["mcp", "token", "Fixture", "Server"])
                remove.assert_called_once_with("Agentnik", credential)
                self.assertEqual(load_config(store.config_path)["mcp_servers"][0]["credential_id"], "")
                self.assertIn("no saved credential", configure_code(store, ["mcp"]))
                with patch("builtins.input", side_effect=["", "https://other.example.org/mcp"]):
                    configure_code(store, ["mcp", "edit-https", "Fixture", "Server"])
                self.assertEqual(load_config(store.config_path)["mcp_servers"][0]["url"],
                                 "https://other.example.org/mcp")
                configure_code(store, ["mcp", "enable", "Fixture", "Server"])
                configure_code(store, ["mcp", "priority", "last"])
                configure_code(store, ["mcp", "timeout", "120", "Fixture", "Server"])
                with self.assertRaises(ValueError):
                    configure_code(store, ["mcp", "timeout", "0", "Fixture", "Server"])
                configure_code(store, ["mcp", "off"])
                saved = load_config(store.config_path)
                self.assertTrue(saved["mcp_servers"][0]["enabled"])
                self.assertEqual(saved["mcp_servers"][0]["timeout_seconds"], 120)
                self.assertEqual(saved["settings"]["mcp_priority"], "last")
                self.assertFalse(saved["settings"]["mcp_access_enabled"])
                with patch("builtins.input", side_effect=[
                    "Local Fixture", "python", '["-m", "fixture"]', "", '{"TOKEN":"MCP_TOKEN"}',
                ]):
                    configure_code(store, ["mcp", "add-local"])
                local = load_config(store.config_path)["mcp_servers"][1]
                self.assertFalse(local["enabled"])
                self.assertEqual(local["args"], ["-m", "fixture"])
                self.assertEqual(local["env"], {"TOKEN": "MCP_TOKEN"})
                configure_code(store, ["mcp", "enable", "Local", "Fixture"])
                configure_code(store, ["mcp", "timeout", "120", "Local", "Fixture"])
                with patch("builtins.input", side_effect=["", "", "not-json", "", ""]):
                    with self.assertRaises(ValueError):
                        configure_code(store, ["mcp", "edit-local", "Local", "Fixture"])
                with patch("builtins.input", side_effect=["Renamed Local", "python3", "[]", "-", "{}"]):
                    configure_code(store, ["mcp", "edit-local", "Local", "Fixture"])
                local = load_config(store.config_path)["mcp_servers"][1]
                self.assertEqual(local["command"], "python3")
                self.assertEqual(local["args"], [])
                self.assertEqual(local["env"], {})
                self.assertTrue(local["enabled"])
                self.assertEqual(local["timeout_seconds"], 120)
                with patch("builtins.input", return_value="y"):
                    configure_code(store, ["mcp", "remove", "Renamed", "Local"])
                self.assertEqual(len(load_config(store.config_path)["mcp_servers"]), 1)
            finally:
                store.db.close()

    def test_bulk_run_limits_preserve_request_timeout_and_context(self):
        from agentnik.code_limits import coding_limits, UNLIMITED_FIELDS, single_request_timeout
        from agentnik.code_settings import configure_code
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                configure_code(store, ["limits", "model_seconds", "180"])
                configure_code(store, ["limits", "context_bytes", "5000"])
                for mode in ("unlimited", "default"):
                    message = configure_code(store, ["limits", "all", mode])
                    reopened = Store(directory)
                    try:
                        actual = reopened.config["settings"]["coding_limits"]
                    finally:
                        reopened.db.close()
                    expected = dict(coding_limits(), model_seconds=180, context_bytes=5000)
                    if mode == "unlimited":
                        expected.update(dict.fromkeys(UNLIMITED_FIELDS, 0))
                    self.assertEqual(actual, expected)
                    self.assertEqual(single_request_timeout(actual), 180)
                    self.assertEqual(single_request_timeout(dict(actual, turn_seconds=60)), 60)
                    for key in UNLIMITED_FIELDS:
                        self.assertIn(f"{key}={expected[key] or 'unlimited'}", message)
                    self.assertIn("Model request timeout (180 s) and context limit (5000 bytes) are unchanged.", message)
            finally:
                store.db.close()

    def test_terminal_composer_completes_nested_commands(self):
        from importlib.util import find_spec

        if find_spec("prompt_toolkit") is None:
            self.skipTest("Terminal composer extra is not installed")
        from prompt_toolkit.completion import CompleteEvent
        from prompt_toolkit.document import Document
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput
        from agentnik.code_composer import create_composer

        with create_pipe_input() as pipe:
            composer = create_composer(input=pipe, output=DummyOutput())
            for partial, expected in (
                ("/resume lat", "/resume latest"),
                ("/open lat", "/open latest"),
                ("/settings mcp sig", "/settings mcp signin"),
                ("/settings web providers s", "/settings web providers set"),
                ("/settings image s", "/settings image set"),
                ("/settings appearance th", "/settings appearance theme"),
                ("/settings goal steps u", "/settings goal steps unlimited"),
                ("/settings limits requests d", "/settings limits requests default"),
                ("/settings web access str", "/settings web access strict_public"),
            ):
                with self.subTest(partial=partial):
                    completions = composer.completer.get_completions(
                        Document(partial), CompleteEvent(completion_requested=True))
                    self.assertIn(expected, [item.text for item in completions])

    def test_terminal_composer_keeps_newlines_and_records_submitted_input(self):
        from importlib.util import find_spec
        import subprocess
        import sys
        from textwrap import dedent

        if find_spec("prompt_toolkit") is None:
            self.skipTest("Terminal composer extra is not installed")
        script = dedent(r"""
            from threading import Timer
            from unittest.mock import patch
            from prompt_toolkit.input import create_pipe_input
            from prompt_toolkit.output import DummyOutput
            from agentnik.code_composer import create_composer, transcript_pager

            with create_pipe_input() as pipe:
                composer = create_composer(input=pipe, output=DummyOutput())
                pipe.send_text("first line\nsecond line\x1b\nthird line\r")
                task = composer.prompt()
                assert task == "first line\nsecond line\nthird line"
                assert composer.history.get_strings() == [task]
                for keys, expected in (("\x1b[A\r", task),
                                       ("draft\x1b[A\x1b[B\r", "draft")):
                    timer = Timer(0.2, pipe.send_text, args=(keys,))
                    timer.start()
                    actual = composer.prompt()
                    timer.join()
                    assert actual == expected, repr(actual)

            with create_pipe_input() as pipe:
                composer = create_composer(input=pipe, output=DummyOutput())
                brief = "Slide brief\n- Main point\n- Supporting facts"
                observed = []

                def on_draft_changed(buffer):
                    if buffer.text == brief:
                        observed.append(buffer.text)
                        pipe.send_text("\r")

                composer.default_buffer.on_text_changed += on_draft_changed
                pipe.send_text("\x1b[200~" + brief.replace("\n", "\r\n") + "\x1b[201~")
                assert composer.prompt() == brief
                assert observed == [brief]

            transcript = "\n".join(f"line {i}" for i in range(100))
            with create_pipe_input() as pipe:
                from contextlib import asynccontextmanager
                from prompt_toolkit.application import in_terminal

                opened = []
                def open_pager(*args, **kwargs):
                    pager = transcript_pager(*args, **kwargs)
                    opened.append(pager)
                    pager.pre_run_callables.append(lambda: pipe.send_text("q"))
                    return pager

                @asynccontextmanager
                async def resume_prompt():
                    async with in_terminal():
                        yield
                    pipe.send_text("\r")

                with patch("agentnik.code_composer.transcript_pager", side_effect=open_pager), \
                        patch("prompt_toolkit.application.in_terminal", resume_prompt):
                    composer = create_composer(transcript=lambda: transcript, input=pipe, output=DummyOutput())
                    pipe.send_text("draft line\nsecond draft line\x14")
                    assert composer.prompt() == "draft line\nsecond draft line"
                assert len(opened) == 1

            for keys, at_end in (("\x1b[5~q", False), ("\x1b[5~\x1b[6~q", True),
                                 ("\x02\x06\x14", True), ("\x15q", False), ("\x15\x04q", True)):
                with create_pipe_input() as pipe:
                    pager = transcript_pager(transcript, input=pipe, output=DummyOutput())
                    pipe.send_text(keys)
                    pager.run()
                    assert (pager.current_buffer.cursor_position == len(transcript)) == at_end

            long_line = "x" * 5000
            with create_pipe_input() as pipe:
                pager = transcript_pager(long_line, input=pipe, output=DummyOutput())
                pipe.send_text("\x1b[5~q")
                pager.run()
                assert 0 < pager.current_buffer.cursor_position < len(long_line)
        """)
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_shell_advice_requires_disclosure_consent_and_skips_credentials(self):
        from threading import Event
        from agentnik.code_terminal import show_shell_advice

        connection = {"url": "http://localhost:11434/v1", "model": "fixture", "api_key": "secret-key"}
        proposal = {"command": "echo OK", "cwd": ".", "shell": "pwsh", "environment_keys": ["PATH"]}
        messages = []
        with patch("agentnik.decision_advice.request", return_value={
            "answers": {"risk": {"choice": "safe", "confidence": 0.8}},
        }) as request:
            with patch("builtins.input", return_value=""):
                show_shell_advice(connection, proposal, Event(), messages.append)
            show_shell_advice(connection, dict(proposal, command="echo secret-key"), Event(), messages.append)
            request.assert_not_called()
            with patch("builtins.input", return_value="y"):
                show_shell_advice(connection, proposal, Event(), messages.append)
            request.assert_called_once()
        self.assertIn("System One advice: SAFE · 80% confidence. You still decide.", messages)

    def test_decision_settings_require_a_binding_and_make_no_requests(self):
        from agentnik.code_settings import configure_code
        from agentnik.storage import Store, load_config

        with TemporaryDirectory() as directory, patch("agentnik.core.open_request") as request:
            store = Store(directory)
            try:
                with self.assertRaises(ValueError):
                    configure_code(store, ["decision", "on"])
                store.save_connection("Fixture", {"url": "http://localhost:11434/v1"})
                with patch("builtins.input", side_effect=["Fixture", "decision-model"]):
                    configure_code(store, ["decision", "set"])
                configure_code(store, ["decision", "on"])
                settings = load_config(store.config_path)["settings"]
                self.assertTrue(settings["decision_advice_enabled"])
                self.assertEqual(settings["decision_model"], {"connection": "Fixture", "model": "decision-model"})
                request.assert_not_called()
            finally:
                store.db.close()

    def test_headless_image_codec_preserves_transparency_without_qt(self):
        from importlib.util import find_spec
        import subprocess
        import sys
        from textwrap import dedent

        if find_spec("PIL") is None:
            self.skipTest("Terminal image extra is not installed")
        script = dedent("""
            import io
            from importlib.abc import MetaPathFinder
            from pathlib import Path
            import sys
            from tempfile import TemporaryDirectory

            class NoQt(MetaPathFinder):
                def find_spec(self, fullname, path, target=None):
                    if fullname == "PySide6":
                        raise ModuleNotFoundError(name=fullname)
                    return None

            sys.meta_path.insert(0, NoQt())
            from PIL import Image
            from agentnik.code_image import convert
            from agentnik.image_generation import image_bytes
            from agentnik.code_agent import ProjectFiles
            from agentnik.code_vision import read_image, image_message

            raw = io.BytesIO()
            Image.new("RGBA", (32, 18), (255, 40, 0, 80)).save(raw, "PNG")
            assert image_bytes(raw.getvalue()) == ("image/png", ".png")
            result = convert(raw.getvalue(), ".webp")
            try:
                convert(raw.getvalue(), ".jpg")
            except ValueError as exc:
                assert "transparency" in str(exc)
            else:
                raise AssertionError("JPEG conversion discarded transparency")
            with Image.open(io.BytesIO(result)) as asset:
                assert asset.size == (32, 18)
                assert asset.getpixel((0, 0))[3] == 80
            with TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                (root / "asset.webp").write_bytes(result)
                data, mime = read_image(ProjectFiles(root), "asset.webp")
                message = image_message([("asset.webp", data, mime)], "chat")
                assert message["content"][1]["image_url"]["url"].startswith("data:image/webp;base64,")
        """)
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_terminal_generates_a_slide_then_sends_it_for_visual_review(self):
        import base64
        import json
        from importlib.util import find_spec
        from unittest.mock import Mock
        from agentnik import cli, core
        from agentnik.storage import Store
        from test_code_agent import call
        from test_compat_tools import chat
        from test_routing import Wire

        if find_spec("PIL") is None:
            self.skipTest("Terminal image extra is not installed")
        from PIL import Image

        pixels = io.BytesIO()
        Image.new("RGB", (160, 90), "blue").save(pixels, format="PNG")
        with TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root, data = base / "project", base / "data"
            root.mkdir()
            store = Store(data)
            try:
                store.save_connection("Fixture", {"url": "https://example.org/v1", "model": "vision", "stream": False})
                store.save_connection("Images", {"url": "https://images.example/v1", "model": "image-default"})
            finally:
                store.db.close()
            composer = Mock()
            composer.prompt.side_effect = ["/connection Fixture", "/settings image set", "/settings image on",
                                           "/vision", "/vision on", "/vision", "Generate and inspect a slide.",
                                           "/vision off", "Continue without image inspection.", "/exit"]
            generate = call("image_gen", {"prompt": "Blue slide", "path": "slide.png", "reference_paths": "[]",
                                          "aspect_ratio": "16:9", "background": "opaque"})
            inspect = call("view_image", {"path": "slide.png"}, ident="call-2")
            argv = ["agentnik", "code", str(root), "--data-dir", str(data)]
            out = io.StringIO()
            replies = iter([
                Wire(chat(calls=[generate], finish="tool_calls"), False),
                Wire(chat(calls=[inspect], finish="tool_calls"), False),
                Wire(chat("Review complete."), False),
                Wire(chat(calls=[inspect], finish="tool_calls"), False),
                Wire(chat("Image inspection is unavailable."), False),
            ])
            requests = []

            def send(connection, url, body, timeout):
                requests.append(json.dumps(body))
                return next(replies)

            with patch("sys.argv", argv), patch("sys.stdin.isatty", return_value=True), \
                    patch("agentnik.code_composer.create_composer", return_value=composer), \
                    patch("builtins.input", side_effect=["Images", "image-model", "", "y"]) as approval, \
                    patch("agentnik.image_generation.generate", return_value={
                        "data": pixels.getvalue(), "mime": "image/png", "suffix": ".png", "cost": None,
                    }) as image_api, \
                    patch.object(core, "open_request", side_effect=send) as model_api, contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(), 0)
            image_api.assert_called_once()
            self.assertEqual(image_api.call_args.args[0]["url"], "https://images.example/v1")
            self.assertEqual(image_api.call_args.args[1], "image-model")
            self.assertTrue(all(call.args[0]["url"] == "https://example.org/v1" for call in model_api.call_args_list))
            self.assertIn("Image inspection is off for this session.", out.getvalue())
            self.assertIn("Image inspection is on for this session.", out.getvalue())
            self.assertIn("Approve once?", approval.call_args.args[0])
            self.assertIn("Approval sends the prompt and any listed reference images", out.getvalue())
            self.assertLess(out.getvalue().index("Approval sends the prompt"),
                            out.getvalue().index("Generating image with the configured image model"))
            self.assertEqual(model_api.call_count, 5, out.getvalue())
            encoded = base64.b64encode((root / "slide.png").read_bytes()).decode()
            self.assertNotIn(encoded, requests[1])
            self.assertIn("data:image/png;base64," + encoded, requests[2])
            tools = json.loads(requests[3])["tools"]
            self.assertNotIn("view_image", {tool["function"]["name"] for tool in tools})
            self.assertIn("Unknown or unavailable tool", requests[4])
            self.assertTrue(all(encoded not in request for request in requests[3:]))
            from agentnik.code_history import CodeHistory

            store = Store(data)
            try:
                saved = [event for record in CodeHistory(store, root).list() for event in record["code_activity"]]
                self.assertIn({"kind": "project_change", "text": "Generated image: slide.png"}, saved)
                self.assertNotIn(encoded, json.dumps(saved))
            finally:
                store.db.close()

    def test_terminal_responses_view_image_sends_render_only_after_tool_call(self):
        self.check_terminal_view_image_transport("responses")

    def test_terminal_messages_view_image_sends_render_only_after_tool_call(self):
        self.check_terminal_view_image_transport("messages")

    def check_terminal_view_image_transport(self, protocol):
        import base64
        import json
        from unittest.mock import Mock
        from agentnik import cli, core
        from agentnik.storage import Store
        from test_compat_tools import msg
        from test_routing import Wire, function_call, message, response
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Terminal image extra is not installed")

        with TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root, data = base / "project", base / "data"
            root.mkdir()
            bad_data = b"not a valid slide render"
            (root / "broken.png").write_bytes(bad_data)
            slide = root / "render.png"
            Image.new("RGB", (160, 90), "blue").save(slide)
            encoded = base64.b64encode(slide.read_bytes()).decode()
            url = "data:image/png;base64," + encoded
            store = Store(data)
            try:
                store.save_connection("Fixture", {"url": "https://example.org/v1", "model": "vision",
                                                   "protocol": protocol, "stream": False})
            finally:
                store.db.close()
            composer = Mock()
            composer.prompt.side_effect = ["/connection Fixture", "/vision on", "Review the rendered slide.", "/exit"]
            if protocol == "responses":
                call = dict(function_call("inspect", '{"path":"render.png"}'), name="view_image")
                invalid = dict(function_call("invalid", '{"path":"broken.png"}'), name="view_image")
                proposal, answer = response([invalid, call]), response([message("Slide reviewed.")])
            else:
                call = {"type": "tool_use", "id": "inspect", "name": "view_image", "input": {"path": "render.png"}}
                invalid = dict(call, id="invalid", input={"path": "broken.png"})
                proposal, answer = msg([invalid, call], "tool_use"), msg([{"type": "text", "text": "Slide reviewed."}])
            replies = iter([Wire(proposal, False), Wire(answer, False)])
            bodies = []
            def send(connection, endpoint, body, timeout):
                bodies.append(json.loads(json.dumps(body)))
                return next(replies)

            with patch("sys.argv", ["agentnik", "code", str(root), "--data-dir", str(data)]), \
                    patch("sys.stdin.isatty", return_value=True), \
                    patch("agentnik.code_composer.create_composer", return_value=composer), \
                    patch.object(core, "open_request", side_effect=send), contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(cli.main(), 0)
            initial, continuation = bodies
            self.assertNotIn(encoded, json.dumps(initial))
            self.assertIn("view_image", {tool.get("name") for tool in initial["tools"]})
            self.assertNotIn(base64.b64encode(bad_data).decode(), json.dumps(continuation))
            if protocol == "responses":
                failure = next(item["output"] for item in continuation["input"]
                               if item.get("type") == "function_call_output" and item.get("call_id") == "invalid")
                self.assertIn("valid PNG, JPEG, and WebP", failure)
                self.assertTrue(any(item.get("type") == "function_call_output" and item.get("call_id") == "inspect"
                                    for item in continuation["input"]))
                self.assertEqual([block["image_url"] for item in continuation["input"]
                                  if isinstance(item.get("content"), list)
                                  for block in item["content"] if block.get("type") == "input_image"], [url])
            else:
                blocks = [block for item in continuation["messages"] if item.get("role") == "user"
                          and isinstance(item.get("content"), list) for block in item["content"]]
                failure = next(block for block in blocks if block.get("type") == "tool_result"
                               and block.get("tool_use_id") == "invalid")
                self.assertIn("valid PNG, JPEG, and WebP", str(failure["content"]))
                result_index = next(index for index, block in enumerate(blocks)
                                    if block.get("type") == "tool_result" and block.get("tool_use_id") == "inspect")
                image_index, = [index for index, block in enumerate(blocks) if block.get("type") == "image"]
                self.assertLess(result_index, image_index)
                self.assertEqual(blocks[image_index]["source"],
                                 {"type": "base64", "media_type": "image/png", "data": encoded})
            self.assertIn("Slide reviewed.", out.getvalue())

    def test_image_settings_reject_an_override_on_another_host(self):
        from agentnik.code_settings import configure_code
        from agentnik.storage import Store, load_config

        with TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                store.save_connection("Fixture", {"url": "https://gateway.example/v1", "protocol": "chat"})
                with patch("builtins.input", side_effect=["Fixture", "image-model", "https://other.example/images"]):
                    with self.assertRaises(ValueError):
                        configure_code(store, ["image", "set"])
                with patch("builtins.input", side_effect=["Fixture", "image-model", ""]):
                    configure_code(store, ["image", "set"])
                configure_code(store, ["image", "on"])
                settings = load_config(store.config_path)["settings"]["image_generation"]
                self.assertEqual(settings, {
                    "enabled": True, "connection": "Fixture", "model": "image-model", "endpoint": "",
                })
                custom = "https://gateway.example/v1/custom/images"
                with patch("builtins.input", side_effect=["", "", custom]):
                    configure_code(store, ["image", "set"])
                with patch("builtins.input", side_effect=["", "new-image-model", ""]):
                    configure_code(store, ["image", "set"])
                self.assertEqual(load_config(store.config_path)["settings"]["image_generation"]["endpoint"], custom)
                self.assertIn("Endpoint: custom override", configure_code(store, ["image"]))
                with patch("builtins.input", side_effect=["", "", "default"]):
                    configure_code(store, ["image", "set"])
                self.assertIn("Endpoint: connection default", configure_code(store, ["image"]))
            finally:
                store.db.close()

    def test_search_credentials_are_saved_in_keyring_and_not_listed(self):
        from agentnik.code_settings import configure_code
        from agentnik.storage import Store, load_config

        with TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                prefix = ["web", "providers"]
                with patch("agentnik.code_settings.getpass", return_value="fixture-key"), \
                        patch("builtins.input", return_value=""), patch("keyring.set_password") as save:
                    configure_code(store, [*prefix, "set", "brave"])
                profile = load_config(store.config_path)["web_backends"][0]
                save.assert_called_once_with("Agentnik Web", profile["credential_id"], "fixture-key")
                self.assertNotIn("api_key", profile)
                self.assertNotIn("fixture-key", configure_code(store, prefix))
                with patch("builtins.input", return_value="y"), patch("keyring.delete_password") as delete:
                    configure_code(store, [*prefix, "remove", "brave-search"])
                delete.assert_called_once_with("Agentnik Web", profile["credential_id"])
                self.assertEqual(load_config(store.config_path)["web_backends"], [])
            finally:
                store.db.close()

    def test_web_opt_in_honors_strict_navigation_without_loading_search_keys(self):
        from unittest.mock import Mock
        from agentnik.code_research import code_research_options

        store = Mock()
        store.config = {"settings": {"research_access_policy": "strict_public"}}
        connection = {"url": "https://gateway.example/v1", "protocol": "chat", "model": "test"}
        self.assertFalse(code_research_options(store, "Fixture", connection, False)["web_enabled"])
        options = code_research_options(store, "Fixture", connection, True)
        self.assertTrue(options["web_enabled"])
        self.assertEqual(options["search_provider"], "none")
        self.assertFalse(options["hosted_search"])
        store.web_backend_specs.assert_not_called()
        store.config["settings"]["research_access_policy"] = "public_fetch"
        store.web_backend_specs.return_value = [{"kind": "ollama"}, {"kind": "brave"}]
        options = code_research_options(store, "Fixture", connection, True)
        self.assertEqual(options["search_provider"], "managed")
        self.assertEqual(options["web_backends"], [{"kind": "brave"}])

    def test_manual_git_diff_only_accepts_the_staged_switch(self):
        from subprocess import CompletedProcess
        from agentnik.code_git_commands import manual_git

        root = Path.cwd()
        with patch("agentnik.code_git_commands.shutil.which", return_value="git"), \
                patch("agentnik.code_git_commands.subprocess.run", return_value=CompletedProcess([], 0)) as run, \
                patch("builtins.input") as prompt:
            manual_git(root, "diff --staged")
            run.assert_called_once_with(
                ["git", "diff", "--no-ext-diff", "--no-textconv", "--staged", "--"],
                cwd=root, check=False, text=True, capture_output=False)
            with self.assertRaises(ValueError):
                manual_git(root, "diff --output=unexpected")
            self.assertEqual(run.call_count, 1)
            prompt.assert_not_called()

    def test_manual_git_commit_and_push_use_explicit_confirmation_and_destination(self):
        import shutil
        import subprocess
        from agentnik.code_git_commands import manual_git

        git = shutil.which("git")
        if not git:
            self.skipTest("Native Git is not installed")
        with TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            root.mkdir()
            remote = Path(directory) / "remote.git"

            def run(*args, cwd=root):
                return subprocess.check_output([git, *args], cwd=cwd, text=True).strip()

            run("init", "--quiet")
            run("init", "--bare", "--quiet", str(remote))
            commits = []
            manual_git(root, "log", write=commits.append)
            self.assertEqual(commits, ["No local commits to show."])
            run("config", "user.name", "Fixture")
            run("config", "user.email", "fixture@example.org")
            run("config", "commit.gpgsign", "false")
            (root / "note draft.txt").write_text("Fixture")
            (root / "other.txt").write_text("Unstaged")
            manual_git(root, 'stage "note draft.txt"', prompt=lambda _: "y")
            self.assertEqual(run("diff", "--cached", "--name-only"), "note draft.txt")
            manual_git(root, "unstage note draft.txt", prompt=lambda _: "y")
            self.assertEqual(run("diff", "--cached", "--name-only"), "")
            manual_git(root, "stage note draft.txt", prompt=lambda _: "y")
            remotes = []
            manual_git(root, "remotes", write=remotes.append)
            self.assertEqual(remotes, ["No Git remotes configured."])
            run("remote", "add", "fixture", str(remote))
            manual_git(root, "remotes", write=remotes.append)
            self.assertEqual(remotes[-1], "fixture")
            nested = root / "nested"
            nested.mkdir()
            review = []
            manual_git(nested, "commit Save fixture", prompt=lambda _: "", write=review.append)
            self.assertIn(f"{run('rev-parse', '--show-toplevel')!r}", review[0])
            self.assertIn("all staged changes", review[0])
            self.assertEqual(run("diff", "--cached", "--name-only"), "note draft.txt")
            manual_git(root, "commit Save fixture", prompt=lambda _: "y", write=lambda _: None)
            self.assertEqual(run("log", "-1", "--format=%s"), "Save fixture")
            manual_git(nested, "log", write=commits.append)
            self.assertEqual(commits[-1], run("log", "-1", "--format=%h %s"))
            manual_git(root, "push fixture release-smoke", prompt=lambda _: "", write=lambda _: None)
            self.assertEqual(run("for-each-ref", cwd=remote), "")
            manual_git(root, "push fixture release-smoke", prompt=lambda _: "y", write=lambda _: None)
            self.assertEqual(run("rev-parse", "refs/heads/release-smoke", cwd=remote), run("rev-parse", "HEAD"))

    def test_terminal_reviews_real_local_git_commit_even_in_allow_all(self):
        from unittest.mock import Mock
        from dulwich import porcelain
        from dulwich.repo import Repo
        from agentnik import cli, core
        from agentnik.storage import Store
        from test_code_agent import call
        from test_compat_tools import chat
        from test_routing import Wire

        with TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root, data = base / "project", base / "data"
            root.mkdir()
            note = root / "note.txt"
            note.write_bytes(b"before\n")
            author = b"Fixture <fixture@example.org>"
            with porcelain.init(root) as repo:
                porcelain.add(repo, [note.name])
                parent = porcelain.commit(repo, message=b"Base", author=author, committer=author,
                                          no_verify=True, sign=False)
            note.write_bytes(b"reviewed\n")
            store = Store(data)
            try:
                store.save_connection("Fixture", {"url": "https://example.org/v1", "model": "fixture", "stream": False})
            finally:
                store.db.close()
            argv = ["agentnik", "code", str(root), "--data-dir", str(data)]
            composer = Mock()
            composer.prompt.side_effect = ["/connection Fixture", "/permissions allow-all",
                                           "/settings git-author set", "Commit the note", "/exit"]
            proposal = call("git_commit", {"paths": '["note.txt"]', "message": "Save reviewed note"})
            output = io.StringIO()
            with patch("sys.argv", argv), patch("sys.stdin.isatty", return_value=True), \
                    patch("agentnik.code_composer.create_composer", return_value=composer), \
                    patch("builtins.input", side_effect=["Terminal Author", "terminal@example.org", "y"]) as prompt, \
                    patch.object(core, "open_request", side_effect=[
                        Wire(chat(calls=[proposal], finish="tool_calls"), False),
                        Wire(chat("Committed."), False),
                    ]), contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(), 0)
            self.assertIn("Approve once?", prompt.call_args.args[0])
            self.assertIn("diff: ", output.getvalue())
            self.assertIn("+reviewed", output.getvalue())
            with Repo(root) as repo:
                commit = repo[repo.head()]
                self.assertEqual(commit.parents, [parent], output.getvalue())
                self.assertEqual(commit.author, b"Terminal Author <terminal@example.org>")
                self.assertEqual(commit.message.strip(), b"Save reviewed note")

    def test_full_cli_turn_applies_reviewed_edit_and_resumes_without_replay(self):
        from importlib.util import find_spec
        from unittest.mock import Mock
        from agentnik import cli, core
        from agentnik.code_history import CodeHistory
        from agentnik.storage import Store
        from test_code_agent import call
        from test_compat_tools import chat
        from test_routing import Wire

        with TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root, data = base / "project", base / "data"
            root.mkdir()
            pdf_commands = []
            if find_spec("pypdf") is not None:
                pdf_fixture().write(root / "reference.pdf")
                pdf_commands.append("/attach reference.pdf")
            asset = Path(cli.__file__).parent / "assets" / "agentnik-icon.png"
            (root / "visual.png").write_bytes(asset.read_bytes())
            (root / "discard.png").write_bytes(asset.read_bytes())
            from zipfile import ZipFile

            brief = root / "slide brief.pptx"
            (base / "outside.txt").write_text("Outside project fixture")
            with ZipFile(brief, "w") as archive:
                archive.writestr("ppt/slides/slide1.xml",
                                 '<a:root xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                                 '<a:t>Presentation fixture brief.</a:t></a:root>')
            skill = root / ".agents" / "skills" / "notes" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("---\nname: notes\ndescription: Note formatting\n---\nFixture note style.\n")
            preserved = root / "keep.txt"
            preserved.write_text("Keep me")
            connection = {"url": "https://gateway.example/v1", "model": "test",
                          "protocol": "chat", "stream": False}
            store = Store(data)
            try:
                store.save_connection("Fixture", connection)
            finally:
                store.db.close()
            argv = ["agentnik", "code", str(root), "--data-dir", str(data)]
            edit = call("write_file", {"path": "note.txt", "content": "reviewed\n"})
            delete = call("delete_file", {"path": "keep.txt"}, ident="call-2")
            auto_edit = call("write_file", {"path": "auto.txt", "content": "automatic\n"})
            shell = call("run_shell", {"path": ".", "command": "echo fixture"}, ident="call-shell")
            first = Mock()
            first.prompt.side_effect = ["/connection Fixture", "/connection Fxture", "/skills add notes",
                                        f'/attach "{base / "outside.txt"}"', f'/attach "{brief}"',
                                        "/model fixture-override", "/model", "/vision on", "/connection Fixture",
                                        "/attach visual.png", "/attach discard.png",
                                        "/attachments", "/attachments remove 3", *pdf_commands,
                                        "/settings limits all unlimited",
                                        "/settngs", "//notes is an example path. Create a note.", "/context", "/context clear",
                                        "/permissions allow-all", "Create another note",
                                        "/scope machine", f'/attach "{brief}"', "/attachments",
                                        "/new", "/status", "/attachments", "/history", "/exit"]
            output = io.StringIO()
            with patch("sys.argv", argv), patch("sys.stdin.isatty", return_value=True), \
                    patch("agentnik.code_composer.create_composer", return_value=first), \
                    patch("builtins.input", side_effect=["y", "n"]) as approval, \
                    patch("agentnik.shell.execute", return_value={
                        "exit_code": 0, "output": "fixture", "truncated": False,
                    }) as execute, \
                    patch.object(core, "open_request", side_effect=[
                        Wire(chat(calls=[edit, delete], finish="tool_calls"), False),
                        Wire(chat("Created the note."), False),
                        Wire(chat(calls=[auto_edit, shell], finish="tool_calls"), False),
                        Wire(chat("Created another note."), False),
                    ]) as transport, contextlib.redirect_stdout(output), \
                    contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(cli.main(), 0)
            self.assertEqual(transport.call_count, 4, output.getvalue())
            before_new, after_new = output.getvalue().split("Started session ", 1)
            self.assertIn("Machine file changes normally skip approval", before_new)
            self.assertIn(brief.name, before_new)
            self.assertIn("Scope: project", after_new)
            self.assertIn("Permissions: require", after_new)
            self.assertIn("Vision: off", after_new)
            self.assertIn("No queued attachments.", after_new)
            self.assertIn("Project file edits, deletions, and generated images require user approval",
                          transport.call_args_list[0].args[2]["messages"][0]["content"])
            self.assertIn("Project file edits and deletions apply without per-file approval",
                          transport.call_args_list[2].args[2]["messages"][0]["content"])
            self.assertIn("No connection with that name.", output.getvalue())
            self.assertIn("Selected model 'fixture-override'.", output.getvalue())
            self.assertIn("Using the connection's default model.", output.getvalue())
            self.assertEqual(transport.call_args_list[0].args[2]["model"], "test")
            self.assertIn("Unknown command.", output.getvalue())
            self.assertIn("/notes is an example path. Create a note.", str(transport.call_args_list[0].args[2]))
            self.assertNotIn("/settngs", str(transport.call_args_list[0].args[2]))
            self.assertIn("Fixture note style.", str(transport.call_args_list[0].args[2]))
            self.assertIn("Presentation fixture brief.", str(transport.call_args_list[0].args[2]))
            if pdf_commands:
                self.assertIn("Headless PDF fixture", str(transport.call_args_list[0].args[2]))
                self.assertNotIn("Headless PDF fixture", str(transport.call_args_list[2].args[2]))
            self.assertIn("Choose an attachment inside the current project.", errors.getvalue())
            self.assertNotIn("Outside project fixture", str(transport.call_args_list[0].args[2]))
            self.assertNotIn("Presentation fixture brief.", str(transport.call_args_list[2].args[2]))
            self.assertIn("data:image/png;base64,", str(transport.call_args_list[0].args[2]))
            self.assertEqual(str(transport.call_args_list[0].args[2]).count("data:image/png;base64,"), 1)
            self.assertIn("Removed queued attachment 'discard.png'.", output.getvalue())
            self.assertNotIn("data:image/png;base64,", str(transport.call_args_list[2].args[2]))
            self.assertIn("Answer:\nCreated the note.", output.getvalue())
            self.assertNotIn("Created the note.", str(transport.call_args_list[2].args[2]))
            execute.assert_called_once()
            self.assertIn("No saved history for this session.", output.getvalue())
            self.assertIn("Permissions: require", output.getvalue())
            self.assertEqual(approval.call_count, 2, output.getvalue())
            self.assertIn("Shell commands that need separate review still prompt.", output.getvalue())
            self.assertEqual((root / "note.txt").read_text(), "reviewed\n")
            self.assertEqual((root / "auto.txt").read_text(), "automatic\n")
            self.assertEqual(preserved.read_text(), "Keep me")
            store = Store(data)
            try:
                session_id, record = next(iter(CodeHistory(store, root).sessions().items()))
                self.assertEqual(record["coding_context"]["answer"], "Created another note.")
                self.assertIn("notes", record["coding_skill_pins"])
                self.assertIn({"kind": "project_change", "text": "Applied project edit: auto.txt"},
                              record["code_activity"])
                from agentnik.sessions import append_code_activity

                for index in range(21):
                    append_code_activity(record, "tool", f"Activity {index}")
                store.save(record)
            finally:
                store.db.close()
            reopened = Mock()
            reopened.prompt.side_effect = ["/history", "/exit"]
            with patch("sys.argv", [*argv, "--resume", session_id[:8]]), \
                    patch("sys.stdin.isatty", return_value=True), \
                    patch("agentnik.code_composer.create_composer", return_value=reopened), \
                    patch.object(core, "open_request") as transport, contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(), 0)
            transport.assert_not_called()
            self.assertIn(f"Resumed session {session_id}", output.getvalue())
            self.assertIn("earlier activity entries omitted", output.getvalue())
            self.assertEqual(output.getvalue().splitlines().count("Create another note"), 2)
            reopened.history.append_string.assert_any_call("Create another note")
            reopened.history.append_string.assert_any_call("//notes is an example path. Create a note.")

    def test_cancel_during_provider_request_saves_session_without_replay(self):
        from queue import Queue
        from threading import Event
        from unittest.mock import Mock
        from agentnik import cli, core
        from agentnik.code_history import CodeHistory
        from agentnik.storage import Store

        entered, release, returned = Event(), Event(), Event()

        def blocked_request(*args, **kwargs):
            entered.set()
            release.wait(10)
            returned.set()
            raise OSError("fixture ended")

        class InterruptQueue(Queue):
            def get(self, *args, **kwargs):
                if not entered.wait(5):
                    raise AssertionError("Provider request did not start")
                raise KeyboardInterrupt

        with TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root, data = base / "project", base / "data"
            root.mkdir()
            store = Store(data)
            try:
                store.save_connection("Fixture", {"url": "https://example.org/v1", "model": "fixture"})
                argv = ["agentnik", "code", str(root), "--data-dir", str(data)]
                composer = Mock()
                composer.prompt.side_effect = ["/connection Fixture", "Interrupted task", "/exit"]
                output = io.StringIO()
                with patch("sys.stdin.isatty", return_value=True), \
                        patch("agentnik.code_composer.create_composer", return_value=composer), \
                        patch("agentnik.code_terminal.Queue", InterruptQueue), \
                        patch.object(core, "open_request", side_effect=blocked_request) as transport, \
                        contextlib.redirect_stdout(output):
                    with patch("sys.argv", argv):
                        self.assertEqual(cli.main(), 0)
                    transport.assert_called_once()
                    self.assertFalse(returned.is_set(), "Cancellation waited for the blocked provider")
                    ident, record = next(iter(CodeHistory(store, root).sessions().items()))
                    self.assertEqual(record["code_state"], "cancelled")
                    self.assertIn("may still finish on its server", record["code_activity"][-1]["text"])
                    composer.prompt.side_effect = ["/exit"]
                    with patch("sys.argv", [*argv, "--resume", ident]):
                        self.assertEqual(cli.main(), 0)
                    transport.assert_called_once()
                self.assertIn("Stopping Code run", output.getvalue())
                self.assertGreaterEqual(output.getvalue().count("will not replay the request"), 2)
                self.assertIn(f"Resumed session {ident}", output.getvalue())
                self.assertEqual(list(root.iterdir()), [])
            finally:
                release.set()
                store.db.close()

    def test_interrupt_at_machine_approval_never_applies_or_replays_edit(self):
        from unittest.mock import Mock
        from agentnik import cli, core
        from agentnik.code_history import CodeHistory
        from agentnik.storage import Store
        from test_code_agent import call
        from test_compat_tools import chat
        from test_routing import Wire

        for interrupt in (KeyboardInterrupt, EOFError):
            with self.subTest(interrupt=interrupt), TemporaryDirectory() as directory:
                base = Path(directory).resolve()
                root, data, target = base / "project", base / "data", base / "outside.txt"
                root.mkdir()
                store = Store(data)
                try:
                    store.save_connection("Fixture", {"url": "https://example.org/v1",
                                                       "model": "fixture", "stream": False})
                    argv = ["agentnik", "code", str(root), "--data-dir", str(data)]
                    composer = Mock()
                    composer.prompt.side_effect = ["/connection Fixture", "/scope machine",
                                                   "Create the outside file", "/exit"]
                    proposal = call("machine_create_file", {"path": str(target), "content": "not approved"})
                    output = io.StringIO()
                    with patch("sys.stdin.isatty", return_value=True), \
                            patch("agentnik.code_composer.create_composer", return_value=composer), \
                            patch("builtins.input", side_effect=interrupt) as approval, \
                            patch.object(core, "open_request", return_value=Wire(
                                chat(calls=[proposal], finish="tool_calls"), False)) as transport, \
                            contextlib.redirect_stdout(output):
                        with patch("sys.argv", argv):
                            self.assertEqual(cli.main(), 0)
                        approval.assert_called_once_with("Approve once? [y/N] ")
                        ident, record = next(iter(CodeHistory(store, root).sessions().items()))
                        self.assertEqual(record["code_state"], "cancelled")
                        composer.prompt.side_effect = ["/exit"]
                        with patch("sys.argv", [*argv, "--resume", ident]):
                            self.assertEqual(cli.main(), 0)
                        transport.assert_called_once()
                    self.assertFalse(target.exists())
                    self.assertIn("will not replay the request", output.getvalue())
                finally:
                    store.db.close()

    def test_resume_rejects_ambiguous_session_prefix(self):
        from agentnik.code_history import resolve_session_id

        sessions = {"abcd-first": {}, "abcd-second": {}, "1234-third": {}}
        with self.assertRaisesRegex(ValueError, "matches multiple sessions"):
            resolve_session_id(sessions, "abcd")
        self.assertEqual(resolve_session_id(sessions, "abcd-s"), "abcd-second")
        self.assertEqual(resolve_session_id(sessions, "latest"), "abcd-first")
        self.assertEqual(resolve_session_id(sessions, "missing"), "")

    def test_failed_startup_resume_does_not_open_a_new_session(self):
        from unittest.mock import Mock
        from agentnik import cli

        with TemporaryDirectory() as directory:
            base = Path(directory)
            composer = Mock()
            composer.prompt.return_value = "/exit"
            argv = ["agentnik", "code", str(base), "--data-dir", str(base / "data"), "--resume", "missing"]
            with patch("sys.argv", argv), patch("sys.stdin.isatty", return_value=True), \
                    patch("agentnik.code_composer.create_composer", return_value=composer), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(), 1)
            composer.prompt.assert_not_called()
            self.assertIn("No saved session with that ID in this project", output.getvalue())

    def test_terminal_keeps_current_session_when_a_settings_file_is_invalid(self):
        import re
        from unittest.mock import Mock
        from agentnik import cli, core
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            data = root / "data"
            store = Store(data)
            try:
                store.save_connection("Fixture", {"url": "https://example.org/v1", "model": "fixture"})
                config_path = store.config_path
                valid = config_path.read_bytes()
            finally:
                store.db.close()
            invalid = b"{invalid fixture"
            commands = iter(["/connection Fixture", "/status", "/settings", "/status", "/settings limits", "/exit"])

            def next_command():
                command = next(commands)
                if command == "/settings":
                    config_path.write_bytes(invalid)
                elif command == "/settings limits":
                    self.assertEqual(config_path.read_bytes(), invalid)
                    config_path.write_bytes(valid)
                return command

            composer = Mock()
            composer.prompt.side_effect = next_command
            argv = ["agentnik", "code", str(root), "--data-dir", str(data)]
            with patch("sys.argv", argv), patch("sys.stdin.isatty", return_value=True), \
                    patch("agentnik.code_composer.create_composer", return_value=composer), \
                    patch.object(core, "open_request") as transport, \
                    contextlib.redirect_stdout(io.StringIO()) as output, \
                    contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(cli.main(), 0)
            transport.assert_not_called()
            ids = re.findall(r"Session: ([a-f0-9-]+) · Connection: 'Fixture'", output.getvalue())
            self.assertEqual(len(ids), 2)
            self.assertEqual(ids[0], ids[1])
            self.assertIn(f"Data directory: {str(data)!r}", output.getvalue())
            self.assertIn("model_seconds:", output.getvalue())
            self.assertTrue(errors.getvalue())

    def test_history_paging_is_scoped_and_does_not_load_prompt_recall(self):
        from unittest.mock import Mock
        from agentnik import cli

        records = [{"code_activity": [{"kind": "prompt", "text": f"Turn {i:02d}"}]} for i in range(21)]
        with TemporaryDirectory() as directory:
            root = Path(directory)
            composer = Mock()
            composer.prompt.side_effect = ["/history", "/history 2", "/history 3", "/history 0", "/exit"]
            argv = ["agentnik", "code", str(root), "--data-dir", str(root / "data")]
            with patch("sys.argv", argv), patch("sys.stdin.isatty", return_value=True), \
                    patch("agentnik.code_composer.create_composer", return_value=composer), \
                    patch("agentnik.code_history.CodeHistory.list", return_value=records) as read, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(), 0)
            first, second = output.getvalue().split("More saved turns are available under /history 2.")
            self.assertIn("Turn 19", first)
            self.assertNotIn("Turn 20", first)
            self.assertIn("Turn 20", second)
            self.assertIn("No saved turns on that page.", second)
            self.assertIn("positive whole page number", second)
            self.assertEqual(read.call_count, 3)
            self.assertEqual(len({args.args[0] for args in read.call_args_list}), 1)
            self.assertTrue(read.call_args.args[0])
            composer.history.append_string.assert_not_called()

    def test_list_sessions_json_without_terminal_does_not_resume(self):
        import json
        from agentnik import cli, core
        from agentnik.code_history import CodeHistory
        from agentnik.code_lease import SessionLease
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            root = Path(directory)
            project, other, data = root / "project", root / "other", root / "data"
            project.mkdir()
            other.mkdir()
            argv = ["agentnik", "code", str(project), "--data-dir", str(data), "--list-sessions"]

            def discover():
                with patch("sys.argv", argv), patch("sys.stdin.isatty", return_value=False), \
                        patch("agentnik.cli.terminal_session") as terminal, patch.object(core, "open_request") as request, \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(cli.main(), 0)
                terminal.assert_not_called()
                request.assert_not_called()
                return json.loads(output.getvalue())

            self.assertEqual(discover(), [])
            self.assertFalse(data.exists())
            store = Store(data)
            ident = str(uuid4())
            try:
                history = CodeHistory(store, project)
                history.start("Fixture", {"model": "test"}, "Private fixture prompt", ident, goal=True)
                CodeHistory(store, other).start("Fixture", {"model": "test"}, "Other project", str(uuid4()))
                (data / "attachments").rmdir()
                with SessionLease(data) as owner:
                    owner.select(ident)
                    with patch("agentnik.storage.load_config", side_effect=AssertionError("configuration not needed")), \
                            patch.object(SessionLease, "select", side_effect=AssertionError("listing must not lease")):
                        listed = discover()
                    self.assertEqual(owner.session_id, ident)
                self.assertFalse((data / "attachments").exists())
                saved, = history.list(ident)
                self.assertEqual(listed, [{"id": ident, "status": "running", "scope": "project",
                                           "goal_status": "active", "updated_at": saved["updated"]}])
                self.assertGreater(listed[0]["updated_at"], 0)
                self.assertEqual(saved["code_state"], "running")
            finally:
                store.db.close()

    def test_unsaved_session_has_status_but_does_not_appear_in_saved_sessions(self):
        from unittest.mock import Mock
        from agentnik import cli, core

        with TemporaryDirectory() as directory:
            root = Path(directory)
            ident = str(uuid4())
            composer = Mock()
            composer.prompt.side_effect = ["/status", "/sessions", "/exit"]
            argv = ["agentnik", "code", str(root), "--data-dir", str(root / "data")]
            with patch("sys.argv", argv), patch("sys.stdin.isatty", return_value=True), \
                    patch("agentnik.cli.uuid4", return_value=ident), \
                    patch("agentnik.code_composer.create_composer", return_value=composer), \
                    patch.object(core, "open_request") as request, contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(), 0)
            self.assertIn(f"Session: {ident}", output.getvalue())
            self.assertIn("Your current session is saved when its first task starts.", output.getvalue())
            self.assertEqual(output.getvalue().count(ident), 1)
            request.assert_not_called()

    def test_session_listing_can_reach_older_pages_without_opening_sessions(self):
        from unittest.mock import Mock
        from agentnik import cli

        saved = {f"fixture-{i:02d}": {"title": f"Saved {i}", "code_state": "completed"} for i in range(21)}
        saved = {ident: (record, "completed" if ident == "fixture-00" else None)
                 for ident, record in saved.items()}
        with TemporaryDirectory() as directory:
            base = Path(directory)
            composer = Mock()
            composer.prompt.side_effect = ["/sessions", "/sessions 2", "/sessions 3", "/sessions 0", "/exit"]
            argv = ["agentnik", "code", str(base), "--data-dir", str(base / "data")]
            with patch("sys.argv", argv), patch("sys.stdin.isatty", return_value=True), \
                    patch("agentnik.cli.uuid4", return_value="fixture-00"), \
                    patch("agentnik.code_composer.create_composer", return_value=composer), \
                    patch("agentnik.code_history.CodeHistory.session_summaries", return_value=saved), \
                    patch("agentnik.code_history.CodeHistory.list") as read_records, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(), 0)
            read_records.assert_not_called()
            first, second = output.getvalue().split("More saved sessions are available under /sessions 2.")
            self.assertIn("fixture-00  completed [current] [goal: completed]  Saved 0", first)
            self.assertIn("fixture-19", first)
            self.assertEqual(first.count("[current]"), 1)
            self.assertNotIn("fixture-20", first)
            self.assertIn("fixture-20", second)
            self.assertNotIn("fixture-19", second)
            self.assertIn("No saved sessions on that page.", second)
            self.assertIn("positive whole page number", second)

    def test_terminal_honors_saved_model_scoped_subagent_capability(self):
        from agentnik.code_settings import configure_code
        from agentnik.code_terminal import load_run_settings, remember_terminal_subagent_rejection
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                store.save_connection("Fixture", {"url": "https://example.org/v1", "model": "fixture"})
                connection = load_run_settings(directory, "Fixture", "")[0]
                remember_terminal_subagent_rejection(directory, "Fixture", connection)
                self.assertEqual(load_run_settings(directory, "Fixture", "")[3]["unsupported_subagent_roles"], {"model"})
                self.assertNotIn("unsupported_subagent_roles", load_run_settings(directory, "Fixture", "other")[3])
                store.update_connection_settings("Fixture", dict(connection, model="replacement"))
                remember_terminal_subagent_rejection(directory, "Fixture", connection)
                self.assertNotIn("unsupported_subagent_roles", load_run_settings(directory, "Fixture", "fixture")[3])
            finally:
                store.db.close()
            connection = load_run_settings(directory, "Fixture", "")[0]
            remember_terminal_subagent_rejection(directory, "Fixture", connection)
            store = Store(directory)
            try:
                self.assertIn("rejections: 1", configure_code(store, ["subagents"]))
                configure_code(store, ["subagents", "reset"])
                self.assertIn("rejections: 0", configure_code(store, ["subagents"]))
                self.assertNotIn("unsupported_subagent_roles", load_run_settings(directory, "Fixture", "")[3])
            finally:
                store.db.close()

    def test_terminal_git_author_override_is_shared_and_project_scoped(self):
        from agentnik.code_settings import configure_code
        from agentnik.code_terminal import load_run_settings
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root, other, data = (base / name for name in ("project", "other", "data"))
            root.mkdir()
            other.mkdir()
            store = Store(data)
            try:
                store.save_connection("Fixture", {"url": "https://example.org/v1", "model": "fixture"})
                with patch("builtins.input", side_effect=["Fixture Author", "author@example.org"]):
                    configure_code(store, ["git-author", "set"], root=root)
                self.assertIn("author@example.org", configure_code(store, ["git-author"], root=root))
                self.assertEqual(load_run_settings(data, "Fixture", "", root=root)[3]["git_author"],
                                 {"name": "Fixture Author", "email": "author@example.org"})
                self.assertNotIn("git_author", load_run_settings(data, "Fixture", "", root=other)[3])
                configure_code(store, ["git-author", "clear"], root=root)
                self.assertIsNone(load_run_settings(data, "Fixture", "", root=root)[3]["git_author"])
                self.assertEqual(list(root.iterdir()), [])
            finally:
                store.db.close()

    def test_terminal_project_memory_reads_desktop_entries_without_crossing_projects(self):
        from agentnik.code_terminal import load_run_settings, terminal_project_memory
        from agentnik.project_memory import ProjectMemory
        from agentnik.repositories import RepositoryRegistry
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root, other, data = (base / name for name in ("project", "other", "data"))
            root.mkdir()
            other.mkdir()
            store = Store(data)
            try:
                registry = RepositoryRegistry(store)
                store.save_connection("Fixture", {"url": "https://example.org/v1", "model": "fixture"})
                memory = ProjectMemory(store.root / "history.sqlite3", registry.put(root))
                saved = memory.save({"title": "Fixture", "text": "Use the local fixture.\x1b[2J",
                                     "source": "README.md", "stale": True})
                self.assertIn(f"{saved['id']}  Fixture [stale]", terminal_project_memory(data, root, ""))
                detail = terminal_project_memory(data, root, f"show {saved['id']}")
                self.assertIn("Source: README.md", detail)
                self.assertNotIn("\x1b", detail)
                self.assertNotIn("project_memory", load_run_settings(data, "Fixture", "", root=root)[3])
                options = load_run_settings(data, "Fixture", "", root=root, memory_enabled=True)[3]
                self.assertTrue(options["project_memory_read_only"])
                self.assertEqual(options["project_memory"].read(saved["id"]), saved)
                self.assertEqual(terminal_project_memory(data, other, ""), "No saved memory for this project.")
                registry.put(other)
                with self.assertRaisesRegex(ValueError, "No memory entry with that ID"):
                    terminal_project_memory(data, other, f"show {saved['id']}")
            finally:
                store.db.close()

    def test_connection_keyring_fallback_requires_explicit_consent(self):
        from keyring.errors import NoKeyringError
        from agentnik.cli import connection_menu
        from agentnik.storage import Store, load_config

        for answer in ("", "y"):
            with self.subTest(answer=answer), TemporaryDirectory() as directory:
                with patch("builtins.input", side_effect=["https://example.org/v1", "", "fixture-model", "", answer]) as prompt, \
                        patch("agentnik.cli.getpass", return_value="fixture-secret"), \
                        patch("keyring.set_password", side_effect=NoKeyringError()) as keyring, \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    connection_menu(directory, "add", "Fixture")
                keyring.assert_called_once()
                self.assertIn("without encryption", prompt.call_args.args[0])
                self.assertNotIn("fixture-secret", output.getvalue())
                store = Store(directory)
                try:
                    saved = load_config(store.config_path)["connections"]
                    if answer:
                        self.assertEqual(saved["Fixture"]["api_key"], "fixture-secret")
                    else:
                        self.assertNotIn("Fixture", saved)
                finally:
                    store.db.close()

    def test_connection_edit_preserves_credential_and_refuses_to_move_it(self):
        from agentnik.cli import connection_menu
        from agentnik.storage import Store, load_config

        with TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            store = Store(directory)
            try:
                store.config["connections"]["Local"] = {
                    "url": "http://localhost:11434/v1", "model": "before",
                    "protocol": "chat", "credential_id": "test-item",
                }
                store.flush()
                with patch("builtins.input", side_effect=["", "", "after"]):
                    connection_menu(directory, "edit", "Local")
                with patch("builtins.input", side_effect=["https://example.org/v1", "", "other"]), \
                        contextlib.redirect_stderr(io.StringIO()) as errors:
                    connection_menu(directory, "edit", "Local")
                self.assertIn("authenticated endpoint", errors.getvalue())
                updated = load_config(store.config_path)["connections"]["Local"]
                self.assertEqual(updated["model"], "after")
                self.assertEqual(updated["credential_id"], "test-item")
                self.assertEqual(updated["url"], "http://localhost:11434/v1")
                with patch("builtins.input", side_effect=["high", "flex", "8192", "off"]):
                    connection_menu(directory, "options", "Local")
                updated = load_config(store.config_path)["connections"]["Local"]
                self.assertEqual(updated["reasoning"], "high")
                self.assertEqual(updated["service_tier"], "flex")
                self.assertEqual(updated["context_limit"], 8192)
                self.assertFalse(updated["stream"])
                self.assertEqual(updated["credential_id"], "test-item")
            finally:
                store.db.close()

    def test_terminal_settings_share_validated_limits_and_tls(self):
        from agentnik.code_settings import configure_code
        from agentnik.storage import Store, load_config

        with TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                configure_code(store, ["limits", "rounds", "12"])
                configure_code(store, ["goal", "steps", "3"])
                configure_code(store, ["web", "desktop", "on"])
                configure_code(store, ["chat-limits", "rounds", "5"])
                with self.assertRaises(ValueError):
                    configure_code(store, ["chat-limits", "rounds", "0"])
                configure_code(store, ["tls", "strict"])
                configure_code(store, ["appearance", "theme", "dark"])
                configure_code(store, ["appearance", "language", "en"])
                configure_code(store, ["appearance", "history", "hide"])
                with self.assertRaises(ValueError):
                    configure_code(store, ["appearance", "font", "100"])
                with self.assertRaises(ValueError):
                    configure_code(store, ["limits", "rounds", "-1"])
                saved = load_config(store.config_path)["settings"]
                self.assertEqual(saved["coding_limits"]["rounds"], 12)
                self.assertEqual(saved["coding_goal_limits"]["steps"], 3)
                self.assertTrue(saved["web_search_enabled"])
                self.assertEqual(saved["chat_research_limits"], {"rounds": 5})
                self.assertFalse(saved["relaxed_tls"])
                self.assertEqual(saved["theme"], "Dark")
                self.assertEqual(saved["language"], "en")
                self.assertFalse(saved["history_visible"])
                configure_code(store, ["limits", "rounds", "default"])
                self.assertNotEqual(load_config(store.config_path)["settings"]["coding_limits"]["rounds"], 12)
            finally:
                store.db.close()

    def test_history_persists_only_completed_context_for_current_project(self):
        from agentnik.code_history import CodeHistory, goal_continuation
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root = base / "project"
            root.mkdir()
            store = Store(base / "settings")
            history = CodeHistory(store, root)
            connection = {"model": "model", "api_key": "synthetic-secret"}
            first, second = str(uuid4()), str(uuid4())
            record, task = history.start("example", connection, "Find synthetic-secret", first)
            self.assertNotIn("coding_context", history.list()[0])
            history.finish(record, task, {"status": "completed", "response_shown": True, "text": "Done"})
            goal, task = history.start("example", connection, "Different task", second, goal=True)
            history.finish(goal, task, {"status": "failed", "limited": True,
                                        "last_goal_detail": "Project state changed before limit.",
                                        "goal_progress": {"steps": 3, "seconds": 2}})
            store.db.close()
            store = Store(base / "settings")
            try:
                history = CodeHistory(store, root)
                restored = history.list(first)[0]
                self.assertEqual(restored["coding_context"], {"task": "Find [redacted]", "answer": "Done"})
                self.assertEqual(set(history.sessions()), {first, second})
                self.assertNotIn("coding_context", history.list(second)[0])
                self.assertEqual(history.list(second)[0]["coding_goal"]["status"], "limited")
                self.assertEqual(history.list(second)[0]["coding_goal_progress"]["steps"], 3)
                continuation = goal_continuation(history.list(second)[0])
                self.assertEqual(continuation["task"], "Different task")
                self.assertIn("Project state changed before limit.", continuation["evidence"])
                self.assertIsNone(goal_continuation(restored))
                self.assertEqual(CodeHistory(store, base).list(), [])
            finally:
                store.db.close()

    def test_stream_holds_partial_credentials_and_renders_once(self):
        key = "test-credential"
        first = visible_prefix("Hello test-cre", [key])
        second = visible_prefix("Hello test-credential!", [key])
        self.assertEqual(first, "Hello ")
        self.assertEqual(second, "Hello [redacted]!")
        self.assertEqual(visible_prefix("aaaa", ["aaa"]), "[redacted]")

        class Run:
            def run(self, emit):
                emit({"kind": "model_delta", "stream_id": "1", "text": first})
                emit({"kind": "model_delta", "stream_id": "1", "text": second[len(first):]})
                emit({"kind": "model_response", "stream_id": "1", "text": second,
                      "thinking": "Provider detail"})
                emit({"kind": "finished", "status": "completed"})

            def stop(self):
                pass

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            drive_run(Run())
        self.assertEqual(output.getvalue(), second + "\nModel thinking:\nProvider detail\n")

    def test_interleaved_activity_does_not_repeat_streamed_response(self):
        from unittest.mock import Mock

        run = Mock()

        def work(emit):
            emit({"kind": "model_delta", "stream_id": "answer", "text": "Already shown."})
            emit({"kind": "output", "text": "Tool activity"})
            emit({"kind": "model_response", "stream_id": "answer", "text": "Already shown. New ending."})
            emit({"kind": "finished", "status": "completed"})

        run.run.side_effect = work
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            drive_run(run)
        self.assertEqual(output.getvalue(), "Already shown.\nTool activity\n New ending.\n")

    def test_interrupted_stream_is_saved_as_activity_not_context(self):
        from unittest.mock import Mock
        from agentnik.code_history import CodeHistory, activity_preview, goal_continuation
        from agentnik.storage import Store

        run = Mock()
        run.run.side_effect = lambda emit: emit(
            {"kind": "model_delta", "stream_id": "partial", "text": "Partial fixture answer."})
        with contextlib.redirect_stdout(io.StringIO()):
            result = drive_run(run)
        self.assertEqual(result["status"], "interrupted")
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            store = Store(root / "data")
            try:
                history = CodeHistory(store, root)
                ident = str(uuid4())
                record, task = history.start("Fixture", {"model": "fixture"}, "Run a goal", ident, goal=True)
                history.finish(record, task, result)
                saved, = history.list(ident)
                self.assertIn("[Incomplete model response]\nPartial fixture answer.", activity_preview(saved))
                self.assertNotIn("coding_context", saved)
                self.assertNotIn("Partial fixture answer.", goal_continuation(saved)["evidence"])
            finally:
                store.db.close()

    def test_terminal_reports_missing_worker_result_without_echoing_exception(self):
        from unittest.mock import Mock

        for failure in (None, RuntimeError("fixture-secret")):
            with self.subTest(failure=failure):
                run = Mock()
                run.run.side_effect = failure
                lines = []
                result = drive_run(run, write=lines.append)
                self.assertEqual(result["kind"], "finished")
                self.assertEqual(result["status"], "interrupted")
                self.assertIn("will not replay the request", result["text"])
                self.assertEqual(lines, [result["text"]])
                self.assertNotIn("fixture-secret", result["text"])
                run.stop.assert_called_once()

    def test_terminal_shows_valid_model_plan_updates_without_requesting_approval(self):
        from unittest.mock import Mock

        run = Mock()
        def work(emit):
            emit({"kind": "plan", "plan": {"explanation": "invalid", "steps": []}})
            emit({"kind": "plan", "plan": {"explanation": "Review visual content.", "steps": [
                {"step": "Render the slide", "status": "completed"},
                {"step": "Inspect the slide", "status": "in_progress"},
            ]}})
            emit({"kind": "finished", "status": "completed"})
        run.run.side_effect = work
        lines = []
        drive_run(run, write=lines.append)
        self.assertEqual("\n".join(lines).splitlines(), ["Plan update (model reported):", "Review visual content.",
                                                        "  [completed] Render the slide", "  [in progress] Inspect the slide"])
        run.decide.assert_not_called()

    def test_prints_notice_when_approval_is_no_longer_pending(self):
        from unittest.mock import Mock

        run = Mock()
        def work(emit):
            emit({"kind": "edit_proposal", "fingerprint": "expired",
                  "proposal": {"path": "note.txt", "diff": "+Not applied"}})
            emit({"kind": "finished", "status": "limited"})
        run.run.side_effect = work
        run.decide.return_value = False
        lines = []
        with patch("builtins.input", return_value="y"):
            result = drive_run(run, write=lines.append)
        run.decide.assert_called_once_with("expired", True)
        self.assertEqual(result["status"], "limited")
        self.assertIn("This approval prompt is no longer active. Your answer was not applied.", lines)

    def test_skips_approval_that_expired_before_display(self):
        from unittest.mock import Mock

        run = Mock()
        def work(emit):
            emit({"kind": "edit_proposal", "fingerprint": "expired",
                  "proposal": {"path": "note.txt", "diff": "+Not applied"}})
            emit({"kind": "finished", "status": "limited"})
        run.run.side_effect = work
        run.approval_pending.return_value = False
        lines = []
        with patch("builtins.input") as prompt:
            result = drive_run(run, write=lines.append)
        run.approval_pending.assert_called_once_with("expired")
        prompt.assert_not_called()
        run.decide.assert_not_called()
        self.assertEqual(result["status"], "limited")
        self.assertEqual(lines, ["Skipped an approval prompt that is no longer active."])

    def test_review_requires_explicit_input_and_escapes_terminal_controls(self):
        class Run:
            decisions = []

            def run(self, emit):
                emit({"kind": "edit_proposal", "fingerprint": "edit",
                      "proposal": {"cwd": "project", "path": "file", "diff": "+\x1b[2J"}})
                emit({"kind": "operation_proposal", "fingerprint": "push",
                      "proposal": {"operation": "git_push_connect"}})
                emit({"kind": "operation_proposal", "fingerprint": "commit",
                      "proposal": {"operation": "git_commit_staged", "paths": ["note.txt"],
                                   "identity": "Fixture <fixture@example.org>", "message": "Save note",
                                   "diff": "+Reviewed note"}})
                emit({"kind": "operation_proposal", "fingerprint": "transfer",
                      "proposal": {"operation": "subagent_file_transfer", "path": "note.txt",
                                   "destination": "https://example.org/v1/responses", "model": "fixture",
                                   "task": "Review note", "payload_bytes": 4, "diff": "Note"}})

            def decide(self, fingerprint, approved):
                self.decisions.append((fingerprint, approved))

            def stop(self):
                pass

        output = io.StringIO()
        run = Run()
        with contextlib.redirect_stdout(output), patch("builtins.input", side_effect=["y", "y", ""]) as prompt:
            drive_run(run)
        self.assertEqual(run.decisions, [("edit", True), ("push", False), ("commit", True), ("transfer", False)])
        self.assertEqual(prompt.call_count, 3)
        self.assertIn("destination: https://example.org/v1/responses", output.getvalue())
        self.assertIn("snapshot: Note", output.getvalue())
        self.assertIn("identity: Fixture <fixture@example.org>", output.getvalue())
        self.assertIn("diff: +Reviewed note", output.getvalue())
        self.assertIn(r"+\x1b[2J", output.getvalue())
        self.assertNotIn("\x1b", output.getvalue())
