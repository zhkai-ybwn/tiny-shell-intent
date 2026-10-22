"""Interactive CLI Demo for Tiny Shell Intent."""

import argparse
import sys
from typing import Optional
from tiny_shell_intent import IntentEngine, format_risk_badge, RiskLevel

# ANSI escape sequences for CLI styling
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def print_banner(engine: IntentEngine) -> None:
    print(f"{CYAN}{BOLD}" + "=" * 68 + f"{RESET}")
    print(f"{CYAN}{BOLD}   Tiny Shell Intent — Windows Command Semantic Recognition (PoC)   {RESET}")
    print(f"{CYAN}{BOLD}" + "=" * 68 + f"{RESET}")
    print(f" {BOLD}Engine:{RESET} Model2Vec (minishlab/potion-base-2M) | Static Embeddings (64-d)")
    print(f" {BOLD}Target:{RESET} Windows PowerShell 7 | Offline In-Memory Search")
    print(f" {BOLD}Knowledge Base:{RESET} {len(engine.store)} intents loaded")
    print(f" {BOLD}Modes:{RESET} hybrid (default), rule, fuzzy, model")
    print(f" {DIM}Commands: ':mode <name>', ':info', ':help', or 'exit' / 'quit' to leave{RESET}")
    print(f"{CYAN}" + "-" * 68 + f"{RESET}\n")


def display_results(result, use_color: bool = True) -> None:
    q = result.query
    latency = result.latency_ms

    if result.is_empty:
        print(f" {YELLOW}Warning: Empty input query. Please enter a command intent.{RESET}\n")
        return

    if result.is_out_of_domain:
        print(f" {YELLOW}[Out-of-Domain / Low Confidence]{RESET} Query '{q}' does not appear to match known shell commands.")
        if not result.candidates:
            print(f" {DIM}No matching shell candidates above threshold.{RESET}\n")
            return
        print(f" {DIM}Showing closest low-confidence fallback candidates:{RESET}")

    print(f"{BOLD}Query:{RESET} \"{q}\"  {DIM}(mode={result.mode}, latency={latency:.2f} ms){RESET}")

    if not result.candidates:
        print(f" {YELLOW}No matching command candidates found.{RESET}\n")
        return

    for rank, cand in enumerate(result.candidates, 1):
        risk_badge = format_risk_badge(cand.risk_level, use_color=use_color)
        src_tag = f"{MAGENTA}[{cand.source.upper()}]{RESET}"
        score_pct = f"{cand.score * 100:.1f}%"

        print(f"\n  {BOLD}{rank}.{RESET} {risk_badge} {src_tag} {CYAN}{BOLD}{cand.command}{RESET}")
        print(f"     {BOLD}Score:{RESET} {score_pct}  |  {BOLD}Category:{RESET} {cand.category}  |  {BOLD}Intent ID:{RESET} {cand.intent_id}")
        print(f"     {BOLD}Desc:{RESET}  {cand.description}")

        if cand.risk_level in (RiskLevel.DANGEROUS.value, RiskLevel.WARNING.value) and cand.risk_reason:
            badge_color = RED if cand.risk_level == RiskLevel.DANGEROUS.value else YELLOW
            print(f"     {badge_color}! Risk Alert: {cand.risk_reason}{RESET}")

    print(f"\n {DIM}[Phase 1 PoC] Candidates are for recommendation only. Execution is disabled.{RESET}\n")


def run_interactive(engine: IntentEngine, initial_mode: str = "hybrid") -> None:
    current_mode = initial_mode
    print_banner(engine)

    while True:
        try:
            prompt = f"{GREEN}tiny-shell ({current_mode})>{RESET} "
            user_input = input(prompt).strip()

            if not user_input:
                continue

            # Command directives
            if user_input.lower() in ("exit", "quit", ":q", ":quit"):
                print(f"{CYAN}Exiting Tiny Shell Intent. Goodbye!{RESET}")
                break

            if user_input.startswith(":mode"):
                parts = user_input.split()
                if len(parts) >= 2 and parts[1].lower() in ("hybrid", "rule", "fuzzy", "model"):
                    current_mode = parts[1].lower()
                    print(f"{GREEN}Switched search mode to: {current_mode}{RESET}\n")
                else:
                    print(f"{YELLOW}Invalid mode. Choose from: hybrid, rule, fuzzy, model{RESET}\n")
                continue

            if user_input in (":help", "help"):
                print(f"{CYAN}Usage:{RESET}")
                print("  Type any command abbreviation or natural language phrase:")
                print("    - 'kill -9'")
                print("    - 'which process uses high cpu'")
                print("    - 'test if port 8080 is listening'")
                print("    - 'rm -rf'")
                print("    - 'how many lines in logfile'")
                print("  Special commands:")
                print("    :mode hybrid | rule | fuzzy | model")
                print("    exit / quit\n")
                continue

            # Execute search
            result = engine.search(user_input, top_k=3, mode=current_mode)
            display_results(result)

        except (KeyboardInterrupt, EOFError):
            print(f"\n{CYAN}Session ended.{RESET}")
            break


def main():
    parser = argparse.ArgumentParser(description="Tiny Shell Intent: Local command semantic recognition CLI.")
    parser.add_argument("query", nargs="?", default=None, help="One-shot query string (optional).")
    parser.add_argument("--mode", default="hybrid", choices=["hybrid", "rule", "fuzzy", "model"], help="Retrieval mode.")
    parser.add_argument("--top-k", type=int, default=3, help="Number of candidates (default: 3).")
    parser.add_argument("--kb", default="data/knowledge_base.json", help="Path to knowledge base JSON.")
    parser.add_argument("--model-path", default="./models/potion-base-2M", help="Path to potion-base-2M weights.")

    args = parser.parse_args()

    engine = IntentEngine(kb_path=args.kb, model_path=args.model_path)

    if args.query:
        result = engine.search(args.query, top_k=args.top_k, mode=args.mode)
        display_results(result)
    else:
        run_interactive(engine, initial_mode=args.mode)


if __name__ == "__main__":
    main()
