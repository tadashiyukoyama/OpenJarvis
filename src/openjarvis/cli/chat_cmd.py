"""``jarvis chat`` — interactive multi-turn chat REPL."""

from __future__ import annotations

import sys
from typing import List, Optional

import click
from rich.console import Console
from rich.markdown import Markdown

from openjarvis.cli._tool_names import resolve_tool_names
from openjarvis.core.config import load_config
from openjarvis.core.events import EventBus
from openjarvis.core.types import Message, Role
from openjarvis.memory import publish_completed_exchange


def _read_input(prompt: str = "You> ") -> Optional[str]:
    """Read user input with graceful EOF handling."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return None


def _run_codex_chat(
    config,
    console: Console,
    bus: EventBus,
    *,
    conversation_id: str,
    conversation_scope: str,
) -> None:
    """Run the interactive chat loop through one Codex system lifecycle."""
    from openjarvis.cli._codex_runtime import build_codex_system
    from openjarvis.core.conversation_identity import ConversationIdentity

    identity = ConversationIdentity(conversation_id, conversation_scope)
    system = build_codex_system(config)
    try:
        console.print(
            "[green bold]OpenJarvis Chat[/green bold]\n"
            "  Engine: [cyan]Codex app-server[/cyan]  "
            "Model: [cyan]external[/cyan]  Agent: [cyan]codex[/cyan]\n"
            "  Type /help for commands, /quit to exit.\n"
        )
        while True:
            user_input = _read_input()
            if user_input is None:
                console.print("\n[dim]Goodbye![/dim]")
                return

            user_input = user_input.strip()
            if not user_input:
                continue

            command = user_input.lower()
            if command in ("/quit", "/exit", "/q"):
                console.print("[dim]Goodbye![/dim]")
                return
            if command == "/help":
                console.print(
                    "[bold]Commands:[/bold]\n"
                    "  /quit, /exit  — end session\n"
                    "  /clear        — start a new identity next time\n"
                    "  /model        — show the external Codex provider\n"
                    "  /help         — this message"
                )
                continue
            if command == "/clear":
                console.print(
                    "[dim]The current Codex thread remains bound. "
                    "Use --conversation-id for a new thread.[/dim]"
                )
                continue
            if command == "/model":
                console.print("Model: [cyan]external Codex provider[/cyan]")
                continue

            try:
                result = system.ask(
                    user_input,
                    context=False,
                    agent="codex",
                    conversation_identity=identity,
                )
                content = result.get("content", "")
                console.print()
                console.print(Markdown(content))
                console.print()
                publish_completed_exchange(
                    bus,
                    user_input,
                    content,
                    source="cli.chat.codex",
                )
            except KeyboardInterrupt:
                console.print("\n[dim]Generation interrupted.[/dim]")
            except Exception as exc:  # noqa: BLE001 - keep the REPL alive
                console.print(f"\n[red]Codex error: {exc}[/red]\n")
    finally:
        system.close()


@click.command()
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option("-m", "--model", "model_name", default=None, help="Model to use.")
@click.option("-a", "--agent", "agent_name", default=None, help="Agent type.")
@click.option("--tools", default=None, help="Comma-separated tool names.")
@click.option("--system", "system_prompt", default=None, help="Custom system prompt.")
@click.option(
    "--persona",
    "persona_name",
    default=None,
    help=(
        "Named persona dir under ~/.openjarvis/personas/<name>/ "
        "(overrides config). Pass 'none' to disable all persona files."
    ),
)
@click.option(
    "--conversation-id",
    default="cli-chat",
    show_default=True,
    help="Stable Codex conversation identity for persistent thread reuse.",
)
@click.option(
    "--conversation-scope",
    default="cli-chat",
    show_default=True,
    help="Scope component of the Codex conversation identity.",
)
def chat(
    engine_key: str | None,
    model_name: str | None,
    agent_name: str | None,
    tools: str | None,
    system_prompt: str | None,
    persona_name: str | None,
    conversation_id: str,
    conversation_scope: str,
) -> None:
    """Start an interactive multi-turn chat session.

    Commands during chat:
      /quit, /exit  — end session
      /clear        — clear conversation history
      /model        — show current model
      /help         — show available commands
      /history      — show conversation history
    """
    console = Console(stderr=True)

    config = load_config()
    bus = EventBus(record_history=False)

    agent_key = agent_name or config.agent.default_agent
    if agent_key == "codex":
        _run_codex_chat(
            config,
            console,
            bus,
            conversation_id=conversation_id,
            conversation_scope=conversation_scope,
        )
        return

    import dataclasses as _dc

    effective_mf = (
        _dc.replace(config.memory_files, persona_name=persona_name)
        if persona_name is not None
        else config.memory_files
    )

    # Resolve engine
    from openjarvis.engine import get_engine
    from openjarvis.intelligence import register_builtin_models

    register_builtin_models()

    resolved = get_engine(config, engine_key)
    if resolved is None:
        console.print("[red]No inference engine available.[/red]")
        sys.exit(1)

    engine_name, engine = resolved
    model = model_name or config.intelligence.default_model
    if not model:
        from openjarvis.engine import discover_engines, discover_models

        all_engines = discover_engines(config)
        all_models = discover_models(all_engines)
        engine_models = all_models.get(engine_name, [])
        if engine_models:
            model = engine_models[0]
        else:
            console.print("[red]No model available.[/red]")
            sys.exit(1)

    # Resolve agent (optional)
    agent = None
    agent_key = agent_name or config.agent.default_agent
    if agent_key and agent_key != "none":
        try:
            import openjarvis.agents  # noqa: F401 — trigger registration
            from openjarvis.core.registry import AgentRegistry

            if AgentRegistry.contains(agent_key):
                agent_cls = AgentRegistry.get(agent_key)
                kwargs: dict = {"bus": bus}

                if getattr(agent_cls, "accepts_tools", False):
                    tool_names_list = resolve_tool_names(
                        tools,
                        getattr(config.tools, "enabled", None),
                        getattr(config.agent, "tools", None),
                    )
                    if tool_names_list:
                        import openjarvis.tools  # noqa: F401 — trigger registration
                        from openjarvis.core.registry import ToolRegistry
                        from openjarvis.tools._stubs import BaseTool

                        tool_instances = []
                        for tname in tool_names_list:
                            if ToolRegistry.contains(tname):
                                tcls = ToolRegistry.get(tname)
                                if isinstance(tcls, type) and issubclass(
                                    tcls, BaseTool
                                ):
                                    tool_instances.append(tcls())
                                elif isinstance(tcls, BaseTool):
                                    tool_instances.append(tcls)
                        if tool_instances:
                            kwargs["tools"] = tool_instances
                    kwargs["max_turns"] = config.agent.max_turns

                    def _confirm(prompt: str) -> bool:
                        console.print(
                            f"[yellow]Confirm:[/yellow] {prompt} [y/N] ",
                            end="",
                        )
                        ans = input().strip().lower()
                        return ans in ("y", "yes")

                    kwargs["interactive"] = True
                    kwargs["confirm_callback"] = _confirm

                import inspect as _inspect

                if (
                    "prompt_builder"
                    in _inspect.signature(agent_cls.__init__).parameters
                ):
                    from openjarvis.prompt.builder import SystemPromptBuilder

                    kwargs["prompt_builder"] = SystemPromptBuilder(
                        agent_template=config.agent.default_system_prompt or "",
                        memory_files_config=effective_mf,
                        system_prompt_config=config.system_prompt,
                    )

                agent = agent_cls(engine, model, **kwargs)
        except Exception as exc:
            console.print(f"[yellow]Agent '{agent_key}' failed: {exc}[/yellow]")

    # Print banner
    console.print(
        f"[green bold]OpenJarvis Chat[/green bold]\n"
        f"  Engine: [cyan]{engine_name}[/cyan]  Model: [cyan]{model}[/cyan]"
        f"  Agent: [cyan]{agent_key or 'direct'}[/cyan]\n"
        f"  Type /help for commands, /quit to exit.\n"
    )

    # Background-work status banner (disappears after first user message)
    from openjarvis.cli._bg_state import get_status
    from openjarvis.cli._chat_banner import render_startup_banner

    _banner = render_startup_banner(get_status())
    if _banner:
        console.print(f"[dim cyan]{_banner}[/dim cyan]")

    # Completion-notification dispatcher (fires once per task per session)
    from openjarvis.cli._chat_notifications import NotificationDispatcher

    _notifications = NotificationDispatcher(get_status())

    # Automatic long-term memory — extracts durable facts in the background.
    memory_service = None
    try:
        from openjarvis.memory import build_memory_service

        memory_service = build_memory_service(config, engine, model, event_bus=bus)
        if memory_service is not None:
            memory_service.start()
            console.print("[dim]  Memory: active[/dim]")
    except Exception as exc:
        console.print(f"[yellow]Memory service unavailable: {exc}[/yellow]")
        memory_service = None

    # Conversation state
    if not system_prompt:
        from openjarvis.prompt.builder import SystemPromptBuilder

        builder = SystemPromptBuilder(
            agent_template=config.agent.default_system_prompt or "",
            memory_files_config=effective_mf,
            system_prompt_config=config.system_prompt,
        )
        system_prompt = builder.build()

    history: List[Message] = []
    if system_prompt:
        history.append(Message(role=Role.SYSTEM, content=system_prompt))

    # REPL loop
    while True:
        for note in _notifications.diff(get_status()):
            console.print(f"[dim cyan]{note}[/dim cyan]")

        user_input = _read_input()
        if user_input is None:
            console.print("\n[dim]Goodbye![/dim]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # Handle slash commands
        cmd = user_input.lower()
        if cmd in ("/quit", "/exit", "/q"):
            console.print("[dim]Goodbye![/dim]")
            break
        elif cmd == "/clear":
            history = []
            if system_prompt:
                history.append(Message(role=Role.SYSTEM, content=system_prompt))
            console.print("[dim]History cleared.[/dim]")
            continue
        elif cmd == "/model":
            console.print(
                f"Model: [cyan]{model}[/cyan]  Engine: [cyan]{engine_name}[/cyan]"
            )
            continue
        elif cmd == "/help":
            console.print(
                "[bold]Commands:[/bold]\n"
                "  /quit, /exit  — end session\n"
                "  /clear        — clear conversation\n"
                "  /model        — show model info\n"
                "  /history      — show conversation\n"
                "  /help         — this message"
            )
            continue
        elif cmd == "/history":
            if not history:
                console.print("[dim]No history yet.[/dim]")
            else:
                for msg in history:
                    role_str = msg.role if isinstance(msg.role, str) else msg.role.value
                    role = role_str.upper()
                    console.print(f"[bold]{role}:[/bold] {msg.content[:200]}")
            continue

        # Add user message
        history.append(Message(role=Role.USER, content=user_input))

        # Generate response
        try:
            if agent is not None:
                response = agent.run(user_input)
                content = (
                    response.content if hasattr(response, "content") else str(response)
                )
            else:
                result = engine.generate(history, model=model)
                content = (
                    result.get("content", "")
                    if isinstance(result, dict)
                    else str(result)
                )

            history.append(Message(role=Role.ASSISTANT, content=content))
            console.print()
            console.print(Markdown(content))
            console.print()

            publish_completed_exchange(
                bus,
                user_input,
                content,
                source="cli.chat",
            )
        except KeyboardInterrupt:
            console.print("\n[dim]Generation interrupted.[/dim]")
        except Exception as exc:
            console.print(f"\n[red]Error: {exc}[/red]\n")

    if memory_service is not None:
        memory_service.stop()


__all__ = ["chat"]
