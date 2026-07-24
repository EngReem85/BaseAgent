"""
BaseAgent: a ReAct agent with decorator-based observability.

Observability uses the same @observe / propagate_attributes API as production Langfuse.
Swapping to real Langfuse requires only changing the import:
    from langfuse import observe, propagate_attributes
"""

import asyncio
import json

import structlog
from litellm import acompletion, completion_cost
from pydantic import ValidationError

from src.agent.prompts import DEFAULT_SYSTEM_PROMPT
from src.config import settings
from src.observability.detectors import LoopDetector
from src.observability.observe import observe, propagate_attributes

logger = structlog.get_logger()


class BaseAgent:
    """
    A ReAct agent with full observability:
    - Decorator-based tracing of every call (@observe)
    - Loop detection (exact, fuzzy, stagnation)
    - Per-run cost tracking
    - Async execution
    """

    def __init__(
        self,
        model: str | None = None,
        max_steps: int = 10,
        agent_name: str = "BaseAgent",
        verbose: bool = True,
        system_prompt: str | None = None,
        tools: list | None = None,
    ):
        self.model = model or settings.model_name
        self.max_steps = max_steps
        self.agent_name = agent_name
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self.verbose = verbose

        self.tools = tools or []
        self.tools_schema = [tool.to_openai_schema() for tool in self.tools]
        self.loop_detector = LoopDetector()

    @observe(name="agent_run", as_type="agent")
    async def run(self, user_query: str) -> dict:
        with propagate_attributes(metadata={"user_query": user_query}):
            # 1. Initialize message history with the system prompt and user query
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_query}
            ]
            
            total_cost = 0.0
            step = 0
            
            # Use propagate_attributes to record model name and metadata
            with propagate_attributes(
                metadata={
                    "agent_name": self.agent_name,
                    "model": self.model,
                    "max_steps": self.max_steps,
                    "user_query": user_query[:100]
                }
            ):
                if self.verbose:
                    logger.info(
                        "agent_started",
                        agent=self.agent_name,
                        model=self.model,
                        max_steps=self.max_steps,
                        tools=[t.name for t in self.tools] if self.tools else []
                    )
                
                try:
                    # 3. Loop up to self.max_steps
                    while step < self.max_steps:
                        # a. Call the LLM with tools and current messages
                        try:
                            response = await acompletion(
                                model=self.model,
                                messages=messages,
                                tools=self.tools_schema if self.tools_schema else None,
                                tool_choice="auto" if self.tools_schema else None,
                                temperature=0.7,
                            )
                        except Exception as e:
                            logger.error("llm_call_failed", error=str(e), step=step)
                            return {
                                "answer": f"LLM call failed at step {step}: {str(e)}",
                                "metadata": {
                                    "steps": step,
                                    "total_cost": total_cost,
                                    "model": self.model,
                                    "agent": self.agent_name,
                                    "error": str(e)
                                }
                            }
                        
                        # b. Track cost/usage from the response
                        try:
                            total_cost += completion_cost(response) or 0.0
                        except Exception:
                            pass
                        
                        # Get the assistant's response
                        assistant_msg = response.choices[0].message
                        
                        # Append assistant message to history
                        messages.append(assistant_msg.model_dump())
                        
                        # c. If the LLM returns a final answer (no tool calls), return it
                        if not assistant_msg.tool_calls:
                            final_answer = assistant_msg.content or "No response generated."
                            
                            if self.verbose:
                                logger.info(
                                    "agent_finished",
                                    agent=self.agent_name,
                                    steps=step + 1,
                                    total_cost=total_cost
                                )
                            
                            return {
                                "answer": final_answer,
                                "metadata": {
                                    "steps": step + 1,
                                    "total_cost": total_cost,
                                    "model": self.model,
                                    "agent": self.agent_name,
                                    "tools_used": [t.name for t in self.tools] if self.tools else []
                                }
                            }
                        
                        # d. If there are tool calls:
                        if self.verbose:
                            logger.info(
                                "tool_calls_made",
                                count=len(assistant_msg.tool_calls),
                                tools=[tc.function.name for tc in assistant_msg.tool_calls]
                            )
                        
                        # Execute tools and collect results
                        tool_results = []
                        for tool_call in assistant_msg.tool_calls:
                            try:
                                tool_name = tool_call.function.name
                                arguments = json.loads(tool_call.function.arguments)
                                
                                # Execute the tool using self._execute_tool
                                result = await self._execute_tool(tool_name, arguments)
                                
                                tool_results.append({
                                    "tool_call_id": tool_call.id,
                                    "role": "tool",
                                    "content": result
                                })
                            except json.JSONDecodeError as e:
                                logger.error("tool_arg_parse_failed", error=str(e))
                                tool_results.append({
                                    "tool_call_id": tool_call.id,
                                    "role": "tool",
                                    "content": f"Error: Failed to parse tool arguments: {e}"
                                })
                            except Exception as e:
                                logger.error("tool_execution_error", error=str(e))
                                tool_results.append({
                                    "tool_call_id": tool_call.id,
                                    "role": "tool",
                                    "content": f"Error executing {tool_name}: {str(e)}"
                                })
                        
                        # Append tool results to history
                        messages.extend(tool_results)
                        step += 1
                    
                    # Max steps reached without final answer
                    return {
                        "answer": "I couldn't reach a final answer within the maximum steps.",
                        "metadata": {
                            "steps": step,
                            "total_cost": total_cost,
                            "model": self.model,
                            "agent": self.agent_name,
                            "error": "max_steps_exceeded"
                        }
                    }
                    
                except Exception as e:
                    logger.error(
                        "agent_failed",
                        agent=self.agent_name,
                        error=str(e),
                        exc_info=True
                    )
                    return {
                        "answer": f"Agent failed: {str(e)}",
                        "metadata": {
                            "steps": step,
                            "total_cost": total_cost,
                            "model": self.model,
                            "agent": self.agent_name,
                            "error": str(e)
                        }
                    }

    @observe(name="tool_call", as_type="tool")
    async def _execute_tool(self, tool_name: str, arguments: dict) -> str:
        """Registry lookup + loop detection + asyncio.to_thread + error handling."""
        loop_check = self.loop_detector.check_tool_call(tool_name, json.dumps(arguments))
        if loop_check.is_looping:
            logger.warning(
                "loop_detected",
                tool=tool_name,
                strategy=loop_check.strategy,
                message=loop_check.message,
            )
            result = f"SYSTEM: {loop_check.message} (Detection: {loop_check.strategy})"
            return result

        tool = next((t for t in self.tools if t.name == tool_name), None)
        if not tool:
            logger.error("tool_not_found", tool=tool_name)
            result = f"Error: Tool '{tool_name}' not found on this agent."
            return result

        try:
            result = str(await asyncio.to_thread(tool.execute, **arguments))
        except ValidationError as e:
            logger.warning("tool_validation_failed", tool=tool_name, error=str(e))
            result = f"Error: Tool arguments validation failed. {e}"
        except Exception as e:
            logger.error("tool_execution_failed", tool=tool_name, error=str(e))
            result = f"Error: {type(e).__name__}: {e}"

        return result