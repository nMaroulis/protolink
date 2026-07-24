#!/usr/bin/env python3
"""Run the Ghost in Lane Four AI Liability Tribunal showcase."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from protolink import Agent, AgentCard, LocalTraceRecorder, LocalTraceTelemetry

try:
    from .courtroom.case_data import ROLE_PROMPTS, juror_system_prompt
    from .courtroom.providers import SUPPORTED_PROVIDERS, model_for_role
    from .courtroom.reporting import write_comparison_index, write_condition_artifacts
    from .courtroom.simulation import CourtroomSimulation, SimulationConfig, summary_from_result
except ImportError:
    from courtroom.case_data import ROLE_PROMPTS, juror_system_prompt
    from courtroom.providers import SUPPORTED_PROVIDERS, model_for_role
    from courtroom.reporting import write_comparison_index, write_condition_artifacts
    from courtroom.simulation import CourtroomSimulation, SimulationConfig, summary_from_result

CONDITIONS = ("solo", "independent", "star", "mesh")
CONDITION_ARTIFACTS = (
    "traces.jsonl",
    "result.json",
    "summary.json",
    "transcript.md",
    "report.html",
)


def _resolve_juror_backend(args: argparse.Namespace) -> tuple[str, str | None, str | None]:
    """Keep provider-specific defaults from leaking across mixed backends."""
    provider = args.juror_provider or args.provider
    same_provider = provider == args.provider
    model = args.juror_model or (args.model if same_provider else None)
    base_url = args.juror_base_url or (args.base_url if same_provider else None)
    return provider, model, base_url


async def run_condition(args: argparse.Namespace, condition: str, condition_dir: Path) -> dict[str, Any]:
    """Construct explicit agents, run one condition, and stop every runtime."""
    condition_dir.mkdir(parents=True, exist_ok=True)
    for artifact_name in CONDITION_ARTIFACTS:
        (condition_dir / artifact_name).unlink(missing_ok=True)

    namespace = _slug(f"{args.run_id}-{condition}")
    recorder = LocalTraceRecorder(path=condition_dir / "traces.jsonl", max_traces=1000)
    telemetry = LocalTraceTelemetry(recorder=recorder, capture_payloads=True)
    juror_provider, juror_model, juror_base_url = _resolve_juror_backend(args)

    # The showcase keeps every actor visible. There is intentionally no generic
    # create_agent() factory hiding the roles or ProtoLink composition surface.
    judge_agent = Agent(
        card=AgentCard(
            name="judge",
            description="Neutral chair of the fictional AI Liability Tribunal.",
            url=f"runtime://ai-liability/{namespace}/judge",
            capabilities={"delegation": True, "has_llm": True, "multi_step_reasoning": True},
            tags=["tribunal", "judge", "procedure"],
        ),
        transport="runtime",
        llm=model_for_role(
            args.provider,
            role="judge",
            seed=args.seed,
            model=args.model,
            base_url=args.base_url,
            temperature=args.temperature,
        ),
        system_prompt=ROLE_PROMPTS["judge"],
        telemetry=telemetry,
        expose_chat=False,
        verbosity=0,
    )
    victim_lawyer_agent = Agent(
        card=AgentCard(
            name="victim_lawyer",
            description="Lawyer for Lina Ortega's family arguing that Aster Vale is guilty.",
            url=f"runtime://ai-liability/{namespace}/victim-lawyer",
            capabilities={"delegation": True, "has_llm": True, "multi_step_reasoning": True},
            tags=["tribunal", "counsel", "victim-advocate"],
        ),
        transport="runtime",
        llm=model_for_role(
            args.provider,
            role="victim_lawyer",
            seed=args.seed,
            model=args.model,
            base_url=args.base_url,
            temperature=args.temperature,
        ),
        system_prompt=ROLE_PROMPTS["victim_lawyer"],
        telemetry=telemetry,
        expose_chat=False,
        verbosity=0,
    )
    manufacturer_agent = Agent(
        card=AgentCard(
            name="manufacturer",
            description="Aster Vale's safety executive and tribunal representative.",
            url=f"runtime://ai-liability/{namespace}/manufacturer",
            capabilities={"delegation": True, "has_llm": True, "multi_step_reasoning": True},
            tags=["tribunal", "manufacturer", "defense"],
        ),
        transport="runtime",
        llm=model_for_role(
            args.provider,
            role="manufacturer",
            seed=args.seed,
            model=args.model,
            base_url=args.base_url,
            temperature=args.temperature,
        ),
        system_prompt=ROLE_PROMPTS["manufacturer"],
        telemetry=telemetry,
        expose_chat=False,
        verbosity=0,
    )
    software_engineer_agent = Agent(
        card=AgentCard(
            name="software_engineer",
            description="Perception engineer who filed the pre-release safety warning.",
            url=f"runtime://ai-liability/{namespace}/software-engineer",
            capabilities={"delegation": True, "has_llm": True},
            tags=["tribunal", "witness", "software-safety"],
        ),
        transport="runtime",
        llm=model_for_role(
            args.provider,
            role="software_engineer",
            seed=args.seed,
            model=args.model,
            base_url=args.base_url,
            temperature=args.temperature,
        ),
        system_prompt=ROLE_PROMPTS["software_engineer"],
        telemetry=telemetry,
        expose_chat=False,
        verbosity=0,
    )
    safety_regulator_agent = Agent(
        card=AgentCard(
            name="safety_regulator",
            description="Regulator who signed the conditional autonomous-vehicle permit.",
            url=f"runtime://ai-liability/{namespace}/safety-regulator",
            capabilities={"delegation": True, "has_llm": True},
            tags=["tribunal", "witness", "regulation"],
        ),
        transport="runtime",
        llm=model_for_role(
            args.provider,
            role="safety_regulator",
            seed=args.seed,
            model=args.model,
            base_url=args.base_url,
            temperature=args.temperature,
        ),
        system_prompt=ROLE_PROMPTS["safety_regulator"],
        telemetry=telemetry,
        expose_chat=False,
        verbosity=0,
    )
    insurance_agent = Agent(
        card=AgentCard(
            name="insurance",
            description="Claims director with an explicit financial interest in loss allocation.",
            url=f"runtime://ai-liability/{namespace}/insurance",
            capabilities={"delegation": True, "has_llm": True},
            tags=["tribunal", "witness", "insurance"],
        ),
        transport="runtime",
        llm=model_for_role(
            args.provider,
            role="insurance",
            seed=args.seed,
            model=args.model,
            base_url=args.base_url,
            temperature=args.temperature,
        ),
        system_prompt=ROLE_PROMPTS["insurance"],
        telemetry=telemetry,
        expose_chat=False,
        verbosity=0,
    )
    accident_investigator_agent = Agent(
        card=AgentCard(
            name="accident_investigator",
            description="Independent investigator reconstructing the interacting failures.",
            url=f"runtime://ai-liability/{namespace}/accident-investigator",
            capabilities={"delegation": True, "has_llm": True},
            tags=["tribunal", "witness", "accident-reconstruction"],
        ),
        transport="runtime",
        llm=model_for_role(
            args.provider,
            role="accident_investigator",
            seed=args.seed,
            model=args.model,
            base_url=args.base_url,
            temperature=args.temperature,
        ),
        system_prompt=ROLE_PROMPTS["accident_investigator"],
        telemetry=telemetry,
        expose_chat=False,
        verbosity=0,
    )
    juror_solo_agent = Agent(
        card=AgentCard(
            name="juror_solo",
            description="Neutral generalist used only for the descriptive solo baseline.",
            url=f"runtime://ai-liability/{namespace}/juror-solo",
            capabilities={"delegation": True, "has_llm": True},
            tags=["tribunal", "juror", "solo-baseline"],
        ),
        transport="runtime",
        llm=model_for_role(
            juror_provider,
            role="juror_solo",
            seed=args.seed,
            model=juror_model,
            base_url=juror_base_url,
            temperature=args.temperature,
        ),
        system_prompt=juror_system_prompt("juror_solo"),
        telemetry=telemetry,
        expose_chat=False,
        verbosity=0,
    )
    juror_evelyn_agent = Agent(
        card=AgentCard(
            name="juror_evelyn",
            description="Former collision detective who reconstructs physical sequences.",
            url=f"runtime://ai-liability/{namespace}/juror-evelyn",
            capabilities={"delegation": True, "has_llm": True},
            tags=["tribunal", "juror", "collision-investigation"],
        ),
        transport="runtime",
        llm=model_for_role(
            juror_provider,
            role="juror_evelyn",
            seed=args.seed,
            model=juror_model,
            base_url=juror_base_url,
            temperature=args.temperature,
        ),
        system_prompt=juror_system_prompt("juror_evelyn"),
        telemetry=telemetry,
        expose_chat=False,
        verbosity=0,
    )
    juror_malik_agent = Agent(
        card=AgentCard(
            name="juror_malik",
            description="Civil-rights lawyer attentive to burden, power, and scapegoating.",
            url=f"runtime://ai-liability/{namespace}/juror-malik",
            capabilities={"delegation": True, "has_llm": True},
            tags=["tribunal", "juror", "burden-of-proof"],
        ),
        transport="runtime",
        llm=model_for_role(
            juror_provider,
            role="juror_malik",
            seed=args.seed,
            model=juror_model,
            base_url=juror_base_url,
            temperature=args.temperature,
        ),
        system_prompt=juror_system_prompt("juror_malik"),
        telemetry=telemetry,
        expose_chat=False,
        verbosity=0,
    )
    juror_anika_agent = Agent(
        card=AgentCard(
            name="juror_anika",
            description="Human-factors psychologist who asks clarifying questions.",
            url=f"runtime://ai-liability/{namespace}/juror-anika",
            capabilities={"delegation": True, "has_llm": True},
            tags=["tribunal", "juror", "human-factors"],
        ),
        transport="runtime",
        llm=model_for_role(
            juror_provider,
            role="juror_anika",
            seed=args.seed,
            model=juror_model,
            base_url=juror_base_url,
            temperature=args.temperature,
        ),
        system_prompt=juror_system_prompt("juror_anika"),
        telemetry=telemetry,
        expose_chat=False,
        verbosity=0,
    )
    juror_ruben_agent = Agent(
        card=AgentCard(
            name="juror_ruben",
            description="Site-reliability engineer focused on controls and failure containment.",
            url=f"runtime://ai-liability/{namespace}/juror-ruben",
            capabilities={"delegation": True, "has_llm": True},
            tags=["tribunal", "juror", "site-reliability"],
        ),
        transport="runtime",
        llm=model_for_role(
            juror_provider,
            role="juror_ruben",
            seed=args.seed,
            model=juror_model,
            base_url=juror_base_url,
            temperature=args.temperature,
        ),
        system_prompt=juror_system_prompt("juror_ruben"),
        telemetry=telemetry,
        expose_chat=False,
        verbosity=0,
    )
    juror_sofia_agent = Agent(
        card=AgentCard(
            name="juror_sofia",
            description="Investigative journalist and jury foreperson.",
            url=f"runtime://ai-liability/{namespace}/juror-sofia",
            capabilities={"delegation": True, "has_llm": True},
            tags=["tribunal", "juror", "foreperson", "journalism"],
        ),
        transport="runtime",
        llm=model_for_role(
            juror_provider,
            role="juror_sofia",
            seed=args.seed,
            model=juror_model,
            base_url=juror_base_url,
            temperature=args.temperature,
        ),
        system_prompt=juror_system_prompt("juror_sofia"),
        telemetry=telemetry,
        expose_chat=False,
        verbosity=0,
    )

    agents = {
        "judge": judge_agent,
        "victim_lawyer": victim_lawyer_agent,
        "manufacturer": manufacturer_agent,
        "software_engineer": software_engineer_agent,
        "safety_regulator": safety_regulator_agent,
        "insurance": insurance_agent,
        "accident_investigator": accident_investigator_agent,
        "juror_solo": juror_solo_agent,
        "juror_evelyn": juror_evelyn_agent,
        "juror_malik": juror_malik_agent,
        "juror_anika": juror_anika_agent,
        "juror_ruben": juror_ruben_agent,
        "juror_sofia": juror_sofia_agent,
    }
    started: list[Agent] = []
    try:
        for agent in agents.values():
            agent.start(background=True)
            started.append(agent)

        actual_model = str(getattr(judge_agent.llm, "model", args.model or "provider-default"))
        actual_juror_model = str(getattr(juror_evelyn_agent.llm, "model", juror_model or "provider-default"))
        provider_label = args.provider if juror_provider == args.provider else f"{args.provider}+jury:{juror_provider}"
        model_label = (
            actual_model if actual_juror_model == actual_model else f"{actual_model}+jury:{actual_juror_model}"
        )
        simulation = CourtroomSimulation(
            agents=agents,
            config=SimulationConfig(
                condition=condition,
                provider=provider_label,
                model=model_label,
                temperature=args.temperature,
                seed=args.seed,
                evidence_order=args.evidence_order,
                rounds=args.rounds,
                max_attempts=args.max_attempts,
                primary_endpoint_mode="custom_cli" if args.base_url else "provider_default_or_environment",
                juror_endpoint_mode="custom_cli" if juror_base_url else "provider_default_or_environment",
                trial_id=f"{args.run_id}-{condition}",
            ),
        )
        result = await simulation.run()
        summary = summary_from_result(result)
        (condition_dir / "result.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (condition_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        write_condition_artifacts(result, condition_dir)
        return result
    finally:
        for agent in reversed(started):
            agent.stop()


async def async_main(args: argparse.Namespace) -> int:
    """Run requested conditions and write a comparison entry point."""
    juror_provider = args.juror_provider or args.provider
    uses_live_provider = args.provider != "reference" or juror_provider != "reference"
    if uses_live_provider and args.condition == "all" and not args.allow_multi_condition_live:
        raise SystemExit(
            "Live-provider `--condition all` can multiply API usage. Select one condition or pass "
            "`--allow-multi-condition-live` explicitly."
        )
    if args.rounds < 0:
        raise SystemExit("--rounds cannot be negative")
    if args.max_attempts not in {1, 2, 3}:
        raise SystemExit("--max-attempts must be 1, 2, or 3")

    output_root = Path(args.output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "index.html").unlink(missing_ok=True)
    conditions = CONDITIONS if args.condition == "all" else (args.condition,)
    provider_label = args.provider if juror_provider == args.provider else f"{args.provider}+jury:{juror_provider}"
    print(f"AI Liability Tribunal · provider={provider_label} · conditions={', '.join(conditions)}")
    print(f"Output: {output_root}")

    results: list[dict[str, Any]] = []
    for condition in conditions:
        print(f"\nRunning {condition} condition...")
        result = await run_condition(args, condition, output_root / condition)
        results.append(result)
        verdict = result["verdict"]
        metrics = result["metrics"]
        print(
            f"  verdict={verdict['verdict'].replace('_', ' ')} "
            f"({verdict['guilty_votes']}-{verdict['not_guilty_votes']}) · "
            f"mean guilt={metrics['final_mean_guilt_probability']:.1f}"
        )

    if len(results) > 1:
        write_comparison_index(results, output_root)
        print(f"\nOpen {output_root / 'index.html'}")
    else:
        print(f"\nOpen {output_root / conditions[0] / 'report.html'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the intentionally small experiment CLI."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    default_output = Path(__file__).resolve().parent / "output" / timestamp
    parser = argparse.ArgumentParser(
        description="Run a replayable AI Liability Tribunal over direct ProtoLink A2A calls.",
    )
    parser.add_argument(
        "--condition",
        choices=(*CONDITIONS, "all"),
        default="all",
        help="Decision condition (default: all, reference provider only).",
    )
    parser.add_argument("--provider", choices=SUPPORTED_PROVIDERS, default="reference")
    parser.add_argument("--model", help="Exact live model id; provider default when omitted.")
    parser.add_argument(
        "--base-url",
        help="Optional provider/server base URL. Required for Ollama unless OLLAMA_URL is set.",
    )
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument(
        "--juror-provider",
        choices=SUPPORTED_PROVIDERS,
        help="Optional juror-only provider; keeps tribunal actors fixed.",
    )
    parser.add_argument("--juror-model", help="Exact model id for --juror-provider.")
    parser.add_argument("--juror-base-url", help="Optional server URL for --juror-provider.")
    parser.add_argument("--seed", type=int, default=7, help="Controls the reference fixture and speaking order.")
    parser.add_argument("--evidence-order", choices=("standard", "reverse"), default="standard")
    parser.add_argument("--rounds", type=int, default=1, help="Number of star/mesh deliberation rounds.")
    parser.add_argument("--max-attempts", type=int, default=2, help="Application-schema attempts per message (1..3).")
    parser.add_argument("--output-dir", default=str(default_output))
    parser.add_argument(
        "--allow-multi-condition-live",
        action="store_true",
        help="Acknowledge the API usage of running every condition with a live provider.",
    )
    parser.add_argument("--run-id", default=f"ghost-lane-four-{timestamp}", help=argparse.SUPPRESS)
    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(async_main(args)))


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")


if __name__ == "__main__":
    main()
