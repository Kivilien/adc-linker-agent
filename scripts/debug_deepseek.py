#!/usr/bin/env python3
"""Debug DeepSeek structured output and tool calling."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def test_basic():
    print("=== 1. Basic chat ===")
    from adc_linker_agent.agent.model_factory import create_model
    from langchain_core.messages import HumanMessage

    model = create_model(temperature=0.2)
    resp = model.invoke([HumanMessage(content="Say 'hello' in one word")])
    print(f"  OK: {resp.content[:50]}")

def test_tool_calling():
    print("\n=== 2. Tool calling ===")
    from adc_linker_agent.agent.model_factory import create_model
    from adc_linker_agent.agent.tools import ALL_TOOLS
    from langchain_core.messages import HumanMessage, SystemMessage

    model = create_model(temperature=0.2, tools=ALL_TOOLS[:2])
    resp = model.invoke([
        SystemMessage(content="You MUST call the validate_smiles tool for any SMILES."),
        HumanMessage(content="Validate this: c1ccccc1")
    ])
    has_tc = bool(getattr(resp, 'tool_calls', None))
    print(f"  Has tool_calls: {has_tc}")
    if has_tc:
        for tc in resp.tool_calls:
            print(f"  Tool: {tc['name']}({tc['args']})")

def test_structured_output():
    print("\n=== 3. Structured output ===")
    from adc_linker_agent.agent.model_factory import create_model
    from langchain_core.messages import HumanMessage
    from pydantic import BaseModel
    from typing import Literal

    class SimpleDecision(BaseModel):
        choice: Literal["A", "B"]
        reason: str

    model = create_model(temperature=0.2, output_schema=SimpleDecision)
    print(f"  Model type: {type(model).__name__}")

    try:
        resp = model.invoke([
            HumanMessage(content="Choose A if you like cats, B if dogs. Explain briefly.")
        ])
        print(f"  Response type: {type(resp).__name__}")
        print(f"  Response: {resp}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

def test_supervisor():
    print("\n=== 4. Supervisor routing ===")
    from adc_linker_agent.agent.model_factory import create_model
    from adc_linker_agent.agent.graph import SupervisorDecision
    from langchain_core.messages import HumanMessage, SystemMessage

    model = create_model(temperature=0.2, output_schema=SupervisorDecision)

    try:
        resp = model.invoke([
            SystemMessage(content="You are a router. Route to property_agent for property questions."),
            HumanMessage(content="Calculate molecular properties of benzene")
        ])
        print(f"  OK: next={resp.next}, reason={resp.reasoning[:60]}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

def test_full_graph():
    print("\n=== 5. Full multi-agent graph ===")
    from adc_linker_agent.agent.graph import get_agent
    from langchain_core.messages import HumanMessage

    graph, config = get_agent(mode="multi", thread_id="debug2")
    state = {"messages": [HumanMessage(content="Calculate properties of benzene (c1ccccc1)")]}

    import time
    start = time.perf_counter()
    result = graph.invoke(state, config)
    elapsed = (time.perf_counter() - start) * 1000

    print(f"  Elapsed: {elapsed:.0f}ms, Messages: {len(result['messages'])}")
    for i, msg in enumerate(result['messages']):
        t = getattr(msg, 'type', '?')
        c = str(getattr(msg, 'content', ''))[:100]
        tc = bool(getattr(msg, 'tool_calls', None))
        print(f"  [{i}] {t}: {c} | tc={tc}")

if __name__ == "__main__":
    test_basic()
    test_tool_calling()
    test_structured_output()
    test_supervisor()
    test_full_graph()
