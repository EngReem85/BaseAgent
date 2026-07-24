""""
Multi-agent orchestration layer.
"""

import asyncio
import structlog

from src.agent.base import BaseAgent
from src.agent.prompts import (
    ANALYST_PROMPT,
    FACT_CHECKER_PROMPT,
    PLANNER_PROMPT,
    RESEARCHER_PROMPT,
    WRITER_PROMPT,
)
from src.config import settings
from src.tools.registry import registry

logger = structlog.get_logger()


class OrchestratorAgent:
    """
    Multi-agent orchestrator with parallel execution.
    Pipeline: (Researcher || FactChecker) → Analyst → Writer
    """

    def __init__(self, model: str = None, max_steps: int = 10):
        resolved_model = model or settings.model_name
        
        # Get tools from registry
        research_tools = registry.get_tools_by_category("research")
        analysis_tools = registry.get_tools_by_category("analysis")
        
        # Initialize agents
        self.researcher = BaseAgent(
            model=resolved_model,
            max_steps=max_steps,
            agent_name="Researcher",
            system_prompt=RESEARCHER_PROMPT,
            tools=research_tools
        )
        
        self.fact_checker = BaseAgent(
            model=resolved_model,
            max_steps=4,
            agent_name="FactChecker",
            system_prompt=FACT_CHECKER_PROMPT,
            tools=research_tools
        )
        
        self.analyst = BaseAgent(
            model=resolved_model,
            max_steps=5,
            agent_name="Analyst",
            system_prompt=ANALYST_PROMPT,
            tools=analysis_tools
        )
        
        self.writer = BaseAgent(
            model=resolved_model,
            max_steps=3,
            agent_name="Writer",
            system_prompt=WRITER_PROMPT,
            tools=[]
        )
        
        logger.info("orchestrator_initialized", model=resolved_model)

    async def run(self, query: str) -> dict:
        logger.info("orchestrator_started", query=query[:100])
        
        try:
            # Step 1: Run Researcher and FactChecker in PARALLEL
            research_task = self.researcher.run(query)
            fact_check_task = self.fact_checker.run(query)
            
            research_result, fact_check_result = await asyncio.gather(
                research_task, fact_check_task, return_exceptions=True
            )
            
            # Handle errors
            research_text = research_result["answer"] if not isinstance(research_result, Exception) else f"Research failed: {research_result}"
            fact_text = fact_check_result["answer"] if not isinstance(fact_check_result, Exception) else f"Fact-check failed: {fact_check_result}"
            
            # Step 2: Synthesize with Analyst
            synthesis_input = f"""
            Query: {query}
            
            Research findings:
            {research_text}
            
            Fact-checking results:
            {fact_text}
            
            Please synthesize these into a comprehensive analysis.
            """
            analysis_result = await self.analyst.run(synthesis_input)
            
            # Step 3: Write final answer
            writer_input = f"Query: {query}\n\nAnalysis:\n{analysis_result['answer']}"
            writer_result = await self.writer.run(writer_input)
            
            # Aggregate metadata
            total_cost = (
                (research_result["metadata"].get("total_cost", 0) if not isinstance(research_result, Exception) else 0) +
                (fact_check_result["metadata"].get("total_cost", 0) if not isinstance(fact_check_result, Exception) else 0) +
                analysis_result["metadata"].get("total_cost", 0) +
                writer_result["metadata"].get("total_cost", 0)
            )
            
            total_steps = (
                (research_result["metadata"].get("steps", 0) if not isinstance(research_result, Exception) else 0) +
                (fact_check_result["metadata"].get("steps", 0) if not isinstance(fact_check_result, Exception) else 0) +
                analysis_result["metadata"].get("steps", 0) +
                writer_result["metadata"].get("steps", 0)
            )
            
            return {
                "answer": writer_result["answer"],
                "metadata": {
                    "total_steps": total_steps,
                    "total_cost": total_cost,
                    "research_steps": research_result["metadata"].get("steps", 0) if not isinstance(research_result, Exception) else 0,
                    "fact_check_steps": fact_check_result["metadata"].get("steps", 0) if not isinstance(fact_check_result, Exception) else 0,
                    "analysis_steps": analysis_result["metadata"].get("steps", 0),
                    "writer_steps": writer_result["metadata"].get("steps", 0),
                    "agents_used": ["Researcher", "FactChecker", "Analyst", "Writer"]
                }
            }
            
        except Exception as e:
            logger.error("orchestrator_failed", error=str(e), exc_info=True)
            return {
                "answer": f"Orchestration failed: {str(e)}",
                "metadata": {"error": str(e)}
            }