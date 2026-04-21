"""
Qwen3.5-27B SPCS — Python API Client Examples
==============================================
Uses the OpenAI Python client against vLLM's OpenAI-compatible server.

Usage:
    pip install openai
    ENDPOINT=https://<spcs-public-url> python3 test/client.py

Get ENDPOINT from:
    make endpoints

Patterns covered:
    1. Basic chat — thinking ON  (default; reasoning field returned)
    2. Chat — thinking OFF       (fast, direct answer, no CoT)
    3. Streaming with reasoning  (reasoning arrives in delta.reasoning)
    4. Tool calling              (multi-turn: define tool → model calls it → inject result → final answer)
"""

import json
import os
import sys
from openai import OpenAI

BASE_URL = os.environ.get("ENDPOINT", "http://localhost:8000")
MODEL    = "qwen3.5-27b"

client = OpenAI(
    base_url=f"{BASE_URL}/v1",
    api_key="not-needed",
)


# ----------------------------------------------------------
# 1. Basic chat completion — thinking ON (Qwen3 default)
#    Response includes:
#      choices[0].message.reasoning  → the <think>...</think> block
#      choices[0].message.content    → final answer
# ----------------------------------------------------------
def example_thinking_on():
    print("\n" + "="*60)
    print("1. Chat completion — thinking ON")
    print("="*60)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "user", "content": "Solve step by step: If 3x + 7 = 22, what is x?"}
        ],
        max_tokens=1024,
    )

    msg = response.choices[0].message
    reasoning = getattr(msg, "reasoning", None)

    print(f"Reasoning ({len(reasoning.split()) if reasoning else 0} words):")
    print(reasoning or "(none)")
    print("\nAnswer:")
    print(msg.content)
    print(f"\nUsage: {response.usage}")


# ----------------------------------------------------------
# 2. Chat completion — thinking OFF
#    Pass enable_thinking=False to skip CoT and get a fast,
#    direct response. Useful when latency matters more than
#    accuracy on simple queries.
# ----------------------------------------------------------
def example_thinking_off():
    print("\n" + "="*60)
    print("2. Chat completion — thinking OFF")
    print("="*60)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "user", "content": "What is the capital of Japan?"}
        ],
        max_tokens=64,
        extra_body={
            "chat_template_kwargs": {"enable_thinking": False}
        },
    )

    print("Answer (no reasoning):")
    print(response.choices[0].message.content)
    print(f"\nUsage: {response.usage}")


# ----------------------------------------------------------
# 3. Streaming with reasoning
#    Reasoning tokens arrive first in delta.reasoning,
#    followed by answer tokens in delta.content.
#    Note: OpenAI Python client doesn't officially type
#    delta.reasoning — use hasattr() to access it safely.
# ----------------------------------------------------------
def example_streaming():
    print("\n" + "="*60)
    print("4. Streaming — reasoning + content")
    print("="*60)

    reasoning_buf = []
    content_buf   = []

    print("Reasoning: ", end="", flush=True)

    with client.chat.completions.stream(
        model=MODEL,
        messages=[
            {"role": "user", "content": "Explain recursion in one concise paragraph."}
        ],
        max_tokens=512,
    ) as stream:
        in_reasoning = True
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            r_token = getattr(delta, "reasoning", None)
            c_token = delta.content or ""

            if r_token:
                reasoning_buf.append(r_token)
                print(r_token, end="", flush=True)
            elif c_token:
                if in_reasoning:
                    print("\nAnswer: ", end="", flush=True)
                    in_reasoning = False
                content_buf.append(c_token)
                print(c_token, end="", flush=True)

    print()
    print(f"\nReasoning total: {len(''.join(reasoning_buf))} chars")
    print(f"Content total:   {len(''.join(content_buf))} chars")


# ----------------------------------------------------------
# 4. Tool calling — multi-turn loop
#    Turn 1: model receives tools + user message, responds
#            with tool_calls (finish_reason="tool_calls")
#    Turn 2: we execute the tool locally, append the result
#            as a "tool" role message, model gives final answer
#
#    Notes:
#    - reasoning and tool calls coexist: reasoning goes in
#      message.reasoning, tool calls in message.tool_calls
#    - tool call arguments are a JSON string; parse with json.loads()
#    - requires server started with:
#        --enable-auto-tool-choice --tool-call-parser hermes
# ----------------------------------------------------------
def example_tool_calling():
    print("\n" + "="*60)
    print("5. Tool calling — multi-turn loop")
    print("="*60)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get the current weather for a given location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "City and state, e.g. San Francisco, CA",
                        },
                        "unit": {
                            "type": "string",
                            "enum": ["celsius", "fahrenheit"],
                        },
                    },
                    "required": ["location"],
                },
            },
        }
    ]

    messages = [
        {"role": "user", "content": "What's the weather like in San Francisco right now?"}
    ]

    # --- Turn 1: model decides to call a tool ---
    response1 = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        max_tokens=512,
    )

    msg1 = response1.choices[0].message
    finish1 = response1.choices[0].finish_reason

    reasoning = getattr(msg1, "reasoning", None)
    print(f"Turn 1 finish_reason: {finish1}")
    print(f"Reasoning: {reasoning or '(none)'}")
    print(f"Tool calls: {msg1.tool_calls}")

    assert msg1.tool_calls, "Expected at least one tool call in turn 1"
    tool_call = msg1.tool_calls[0]
    fn_name   = tool_call.function.name
    fn_args   = json.loads(tool_call.function.arguments)
    print(f"\nExecuting: {fn_name}({fn_args})")

    # --- Execute tool locally (stub) ---
    tool_result = f"72°F and sunny in {fn_args.get('location', 'unknown')}"
    print(f"Tool result: {tool_result}")

    # --- Turn 2: feed result back, get final answer ---
    messages.append(msg1)          # assistant message with tool_calls
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": tool_result,
    })

    response2 = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=tools,
        max_tokens=256,
    )

    msg2 = response2.choices[0].message
    print(f"\nTurn 2 finish_reason: {response2.choices[0].finish_reason}")
    print(f"Final answer: {msg2.content}")
    print(f"Usage: {response2.usage}")


if __name__ == "__main__":
    examples = {
        "1": example_thinking_on,
        "2": example_thinking_off,
        "3": example_streaming,
        "4": example_tool_calling,
    }

    if len(sys.argv) > 1:
        fn = examples.get(sys.argv[1])
        if fn:
            fn()
        else:
            print(f"Unknown example: {sys.argv[1]}. Choose from: {list(examples)}")
            sys.exit(1)
    else:
        for fn in examples.values():
            fn()
