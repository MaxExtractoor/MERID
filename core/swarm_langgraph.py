"""LangGraph integration for stateful agent workflows in MERID."""

from typing import TypedDict, List, Dict, Any, Annotated
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
import operator
import structlog

logger = structlog.get_logger(__name__)


class AgentState(TypedDict):
    """State maintained across agent workflow."""
    messages: Annotated[List[BaseMessage], operator.add]
    trade_signal: Dict[str, Any]
    risk_approved: bool
    execution_result: Dict[str, Any]
    next_step: str


def create_trading_workflow() -> StateGraph:
    """Create a LangGraph workflow for trading execution."""
    
    workflow = StateGraph(AgentState)
    
    # Define nodes
    def analysis_node(state: AgentState) -> AgentState:
        """Analyze market and generate trade signal."""
        logger.info("analysis_node_executing", signal=state.get("trade_signal"))
        return {
            **state,
            "messages": [AIMessage(content="Analysis complete: Bullish signal detected")],
            "next_step": "risk_check"
        }
    
    def risk_node(state: AgentState) -> AgentState:
        """Risk assessment and approval."""
        signal = state.get("trade_signal", {})
        confidence = signal.get("confidence", 0)
        
        # Risk logic: require confidence > 0.7
        approved = confidence > 0.7
        
        logger.info("risk_node_executing", approved=approved, confidence=confidence)
        
        return {
            **state,
            "risk_approved": approved,
            "messages": [AIMessage(content=f"Risk check: {'APPROVED' if approved else 'REJECTED'}")],
            "next_step": "execute" if approved else END
        }
    
    def execution_node(state: AgentState) -> AgentState:
        """Execute trade via venue APIs."""
        logger.info("execution_node_executing", signal=state.get("trade_signal"))
        return {
            **state,
            "execution_result": {"status": "filled", "order_id": "mock-123"},
            "messages": [AIMessage(content="Trade executed successfully")],
            "next_step": END
        }
    
    # Add nodes to graph
    workflow.add_node("analysis", analysis_node)
    workflow.add_node("risk_check", risk_node)
    workflow.add_node("execute", execution_node)
    
    # Define edges
    workflow.set_entry_point("analysis")
    workflow.add_edge("analysis", "risk_check")
    workflow.add_conditional_edges(
        "risk_check",
        lambda state: state["next_step"],
        {
            "execute": "execute",
            END: END
        }
    )
    workflow.add_edge("execute", END)
    
    return workflow.compile()


class LangGraphTradingSwarm:
    """MERID Trading Swarm using LangGraph for stateful workflows."""
    
    def __init__(self):
        self.workflow = create_trading_workflow()
        self.logger = logger.bind(component="LangGraphTradingSwarm")
    
    async def execute_trade(self, trade_signal: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a trade through the LangGraph workflow."""
        initial_state: AgentState = {
            "messages": [HumanMessage(content=f"Execute trade: {trade_signal}")],
            "trade_signal": trade_signal,
            "risk_approved": False,
            "execution_result": {},
            "next_step": ""
        }
        
        self.logger.info("workflow_started", signal=trade_signal.get("symbol"))
        
        # Run the workflow
        final_state = self.workflow.invoke(initial_state)
        
        self.logger.info(
            "workflow_completed",
            approved=final_state["risk_approved"],
            result=final_state.get("execution_result")
        )
        
        return {
            "approved": final_state["risk_approved"],
            "execution": final_state.get("execution_result"),
            "messages": [m.content for m in final_state["messages"]]
        }
