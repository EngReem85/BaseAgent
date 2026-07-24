import asyncio
import json
import sys
from datetime import datetime
from typing import Optional

import structlog
import typer
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich.markdown import Markdown

from src.agent.orchestration import OrchestratorAgent
from src.config import settings
from src.logger import configure_logging

configure_logging()
logger = structlog.get_logger()
console = Console()

app = typer.Typer(help="AI Research Agent CLI")


@app.command()
def research(
    query: str = typer.Argument(..., help="The research query to run."),
    model: str = typer.Option(None, "--model", "-m", help="LLM model to use (overrides settings)."),
    max_steps: int = typer.Option(settings.max_steps, "--max-steps", "-s", help="Max ReAct steps."),
):
    """Run the AI research agent on a query."""
    resolved_model = model or settings.model_name
    agent = OrchestratorAgent(model=resolved_model, max_steps=max_steps)
    result = asyncio.run(agent.run(query))
    print(result["answer"])


@app.command()
def compare(
    query: str = typer.Argument(..., help="The research query to run."),
    models: list[str] = typer.Option(
        ["openrouter/free", "groq/llama-3.3-70b-versatile"],
        "--models",
        "-m",
        help="List of models to compare (space-separated).",
    ),
    max_steps: int = typer.Option(3, "--max-steps", "-s", help="Max ReAct steps per model."),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save results to JSON file."),
):
    """
    Compare multiple LLM models on the same query.
    """
    console.print(f"\n[bold cyan]🔍 Comparing {len(models)} models[/bold cyan]")
    console.print(f"📝 Query: {query}\n")
    
    results = []
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        
        for i, model in enumerate(models):
            task = progress.add_task(
                f"[yellow]Testing {model}...[/yellow]",
                total=None
            )
            
            try:
                agent = OrchestratorAgent(model=model, max_steps=max_steps)
                result = asyncio.run(agent.run(query))
                
                results.append({
                    "model": model,
                    "answer": result["answer"],
                    "metadata": result["metadata"],
                    "status": "success"
                })
                
                progress.update(task, description=f"[green]✅ {model} - Completed[/green]")
                
            except Exception as e:
                results.append({
                    "model": model,
                    "answer": None,
                    "metadata": {},
                    "status": "failed",
                    "error": str(e)
                })
                progress.update(task, description=f"[red]❌ {model} - Failed: {str(e)[:50]}[/red]")
    
    display_comparison_results(results, query)
    
    if output:
        save_results(results, query, output)
    
    return results


@app.command()
def verify(
    query: str = typer.Argument(
        "Compare the capabilities, strengths, and weaknesses of different LLM models",
        help="The query to verify the system with."
    ),
    models: list[str] = typer.Option(
        ["openrouter/free", "groq/llama-3.3-70b-versatile"],
        "--models",
        "-m",
        help="List of models to test (space-separated).",
    ),
    max_steps: int = typer.Option(3, "--max-steps", "-s", help="Max ReAct steps per model."),
    output: Optional[str] = typer.Option(
        "verification_report.json",
        "--output",
        "-o",
        help="Save verification report to JSON file."
    ),
):
    """
    Verify the system by running a full comparison and generating a comprehensive report.
    
    This command:
    1. Tests multiple LLM models on a query
    2. Generates a detailed comparison report
    3. Saves results to a JSON file
    4. Provides a summary of system status
    
    Examples:
    
    # Run verification with default settings
    python -m src.main verify
    
    # Run verification with custom models
    python -m src.main verify --models groq/llama-3.3-70b-versatile openrouter/free deepseek/deepseek-r1:free
    
    # Run verification with custom query
    python -m src.main verify "What are the best AI models for code generation?"
    """
    
    console.print(Panel.fit(
        "[bold cyan]🔬 SYSTEM VERIFICATION[/bold cyan]",
        border_style="cyan"
    ))
    
    console.print(f"\n[bold]📝 Query:[/bold] {query}")
    console.print(f"[bold]🔄 Models to test:[/bold] {len(models)}")
    for model in models:
        console.print(f"   • {model}")
    console.print(f"[bold]📊 Max steps per model:[/bold] {max_steps}")
    
    # Run comparison
    results = asyncio.run(_run_verification(query, models, max_steps))
    
    # Generate report
    console.print("\n[bold cyan]📋 GENERATING VERIFICATION REPORT[/bold cyan]")
    
    report = generate_verification_report(results, query, models, max_steps)
    
    # Display report
    display_verification_report(report)
    
    # Save report
    if output:
        save_verification_report(report, output)
    
    # Return status
    success_count = sum(1 for r in results if r["status"] == "success")
    total_count = len(results)
    
    if success_count == total_count:
        console.print("\n[bold green]✅ VERIFICATION PASSED[/bold green] - All models completed successfully!")
    elif success_count > 0:
        console.print(f"\n[bold yellow]⚠️ VERIFICATION PARTIAL[/bold yellow] - {success_count}/{total_count} models succeeded")
    else:
        console.print("\n[bold red]❌ VERIFICATION FAILED[/bold red] - No models completed successfully")
        console.print("[red]Check your API keys and network connection.[/red]")
    
    console.print(f"\n[dim]Report saved to: {output}[/dim]" if output else "")
    
    return results


async def _run_verification(query: str, models: list[str], max_steps: int) -> list:
    """Run verification comparison asynchronously."""
    results = []
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        
        for model in models:
            task = progress.add_task(
                f"[yellow]Testing {model}...[/yellow]",
                total=None
            )
            
            try:
                agent = OrchestratorAgent(model=model, max_steps=max_steps)
                result = await agent.run(query)
                
                results.append({
                    "model": model,
                    "answer": result["answer"],
                    "metadata": result["metadata"],
                    "status": "success"
                })
                
                progress.update(task, description=f"[green]✅ {model} - Completed[/green]")
                
            except Exception as e:
                error_msg = str(e)
                results.append({
                    "model": model,
                    "answer": None,
                    "metadata": {},
                    "status": "failed",
                    "error": error_msg
                })
                progress.update(task, description=f"[red]❌ {model} - Failed[/red]")
    
    return results


def generate_verification_report(results: list, query: str, models: list[str], max_steps: int) -> dict:
    """Generate a comprehensive verification report."""
    
    successful = [r for r in results if r["status"] == "success"]
    failed = [r for r in results if r["status"] == "failed"]
    
    report = {
        "timestamp": datetime.now().isoformat(),
        "verification_type": "llm_comparison",
        "query": query,
        "models_tested": models,
        "max_steps": max_steps,
        "summary": {
            "total_models": len(results),
            "successful": len(successful),
            "failed": len(failed),
            "success_rate": f"{len(successful)/len(results)*100:.1f}%" if results else "0%"
        },
        "model_results": results,
        "comparison_metrics": {
            "fastest_model": None,
            "most_accurate": None,
            "lowest_cost": None,
            "average_cost": 0,
            "average_steps": 0
        }
    }
    
    # Calculate metrics for successful models
    if successful:
        # Find fastest (least steps)
        fastest = min(successful, key=lambda x: x["metadata"].get("steps", float('inf')))
        report["comparison_metrics"]["fastest_model"] = fastest["model"]
        
        # Find lowest cost
        cheapest = min(successful, key=lambda x: x["metadata"].get("total_cost", float('inf')))
        report["comparison_metrics"]["lowest_cost"] = cheapest["model"]
        
        # Calculate averages
        total_cost = sum(r["metadata"].get("total_cost", 0) for r in successful)
        total_steps = sum(r["metadata"].get("steps", 0) for r in successful)
        report["comparison_metrics"]["average_cost"] = total_cost / len(successful)
        report["comparison_metrics"]["average_steps"] = total_steps / len(successful)
    
    # Add recommendations
    if successful:
        best_overall = min(successful, key=lambda x: x["metadata"].get("total_cost", float('inf')))
        report["recommendations"] = {
            "best_model": best_overall["model"],
            "reason": f"Lowest cost ({best_overall['metadata'].get('total_cost', 0):.6f}) with {best_overall['metadata'].get('steps', 0)} steps",
            "alternative": fastest["model"] if fastest else None
        }
    else:
        report["recommendations"] = {
            "best_model": None,
            "reason": "No models completed successfully",
            "suggestion": "Check API keys, network connection, and model availability"
        }
    
    return report


def display_verification_report(report: dict):
    """Display the verification report in a user-friendly format."""
    
    console.print("\n[bold cyan]📊 VERIFICATION REPORT[/bold cyan]")
    console.print("=" * 80)
    
    # Summary
    summary = report["summary"]
    console.print(f"\n[bold]Summary:[/bold]")
    console.print(f"  • Total Models Tested: {summary['total_models']}")
    console.print(f"  • Successful: [green]{summary['successful']}[/green]")
    console.print(f"  • Failed: [red]{summary['failed']}[/red]")
    console.print(f"  • Success Rate: {summary['success_rate']}")
    
    # Metrics
    metrics = report["comparison_metrics"]
    if metrics["fastest_model"]:
        console.print(f"\n[bold]Performance Metrics:[/bold]")
        console.print(f"  • Fastest Model: [cyan]{metrics['fastest_model']}[/cyan]")
        console.print(f"  • Lowest Cost: [cyan]{metrics['lowest_cost']}[/cyan]")
        console.print(f"  • Average Cost: [cyan]${metrics['average_cost']:.6f}[/cyan]")
        console.print(f"  • Average Steps: [cyan]{metrics['average_steps']:.1f}[/cyan]")
    
    # Recommendations
    recommendations = report.get("recommendations", {})
    if recommendations.get("best_model"):
        console.print(f"\n[bold green]🏆 Recommendation:[/bold green]")
        console.print(f"  Best Model: [bold cyan]{recommendations['best_model']}[/bold cyan]")
        console.print(f"  Reason: {recommendations['reason']}")
    elif recommendations.get("suggestion"):
        console.print(f"\n[bold yellow]💡 Suggestion:[/bold yellow]")
        console.print(f"  {recommendations['suggestion']}")
    
    # Detailed results
    console.print("\n[bold]Detailed Model Results:[/bold]")
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Model", style="cyan")
    table.add_column("Status")
    table.add_column("Steps")
    table.add_column("Cost", justify="right")
    table.add_column("Answer Preview")
    
    for result in report["model_results"]:
        status = "✅ Success" if result["status"] == "success" else "❌ Failed"
        steps = str(result["metadata"].get("steps", "-")) if result["status"] == "success" else "-"
        cost = f"${result['metadata'].get('total_cost', 0):.6f}" if result["status"] == "success" else "-"
        
        preview = ""
        if result["status"] == "success" and result["answer"]:
            preview = result["answer"][:100] + "..." if len(result["answer"]) > 100 else result["answer"]
        elif result["status"] == "failed":
            preview = result.get("error", "Unknown error")[:100]
        
        table.add_row(
            result["model"],
            status,
            steps,
            cost,
            preview
        )
    
    console.print(table)
    
    # System health
    console.print("\n[bold]System Health:[/bold]")
    if summary["successful"] == summary["total_models"]:
        console.print("  [green]✅ All systems operational[/green]")
    elif summary["successful"] > 0:
        console.print("  [yellow]⚠️ Partial system functionality[/yellow]")
    else:
        console.print("  [red]❌ System failure - check configuration[/red]")
    
    console.print("\n" + "=" * 80)


def save_verification_report(report: dict, filename: str):
    """Save verification report to JSON file."""
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    console.print(f"\n[green]✅ Verification report saved to: {filename}[/green]")


def display_comparison_results(results: list, query: str):
    """Display comparison results."""
    # ... (same as before)
    pass


def save_results(results: list, query: str, filename: str):
    """Save comparison results to JSON file."""
    # ... (same as before)
    pass


@app.command()
def info():
    """Show information about the current configuration."""
    console.print("\n[bold cyan]🔧 CURRENT CONFIGURATION[/bold cyan]")
    console.print("=" * 50)
    console.print(f"  Model: {settings.model_name}")
    console.print(f"  Max Steps: {settings.max_steps}")
    console.print(f"  Log Level: {settings.log_level}")
    
    # Check API keys
    console.print("\n[bold]API Keys:[/bold]")
    import os
    keys = {
        "OPENROUTER_API_KEY": "OpenRouter",
        "GROQ_API_KEY": "Groq",
        "OPENAI_API_KEY": "OpenAI",
        "CEREBRAS_API_KEY": "Cerebras"
    }
    for env_var, name in keys.items():
        status = "✅" if os.getenv(env_var) else "❌"
        console.print(f"  {status} {name}")


@app.command()
def version():
    """Show version information."""
    import sys
    from importlib.metadata import version as get_version
    
    try:
        ver = get_version("ai-agents-starter")
    except Exception:
        ver = "development"
    
    console.print(f"[bold cyan]AI Research Agent v{ver}[/bold cyan]")
    console.print(f"Python {sys.version}")
    console.print(f"Settings loaded from: .env")


if __name__ == "__main__":
    app()