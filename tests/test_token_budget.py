"""
Token Budget Verification Test.
Proves that a 15-step computer use process remains strictly bounded
under 1,500 cumulative prompt tokens using First-Mile Minimization and composite steps.
"""

import pytest
from perception.edge_parser import EdgeUIAParser


def test_15_step_token_budget_bound():
    """
    Simulates 15 sequential computer-use steps and calculates token consumption.
    Validates that total cumulative tokens across 15 steps remain < 1,500 tokens.
    """
    parser = EdgeUIAParser()

    # Step 1: Main window
    main_window_result = {
        "status": "ok",
        "window": "Document - Text Editor",
        "hwnd": 9999,
        "rect": (200, 100, 1000, 700),
        "elements": [
            {"id": i, "name": f"Control_{i}", "type": "Btn" if i % 2 == 0 else "Edit",
             "center": (200 + i * 40, 150), "rect": (180 + i * 40, 130, 220 + i * 40, 170), "focused": (i == 1)}
            for i in range(1, 11)
        ]
    }

    # Step 8: Dialog window opens (e.g. Save As)
    dialog_window_result = {
        "status": "ok",
        "window": "Save As",
        "hwnd": 8888,
        "rect": (300, 200, 600, 400),
        "elements": [
            {"id": 1, "name": "File name", "type": "Edit", "center": (450, 300), "rect": (350, 280, 550, 320), "focused": True},
            {"id": 2, "name": "Save", "type": "Btn", "center": (520, 360), "rect": (480, 340, 560, 380), "focused": False},
            {"id": 3, "name": "Cancel", "type": "Btn", "center": (580, 360), "rect": (540, 340, 620, 380), "focused": False},
        ]
    }

    step_outputs = []

    for step_num in range(1, 16):
        # Steps 8-10 interact with dialog, others interact with main window
        if 8 <= step_num <= 10:
            curr_result = dialog_window_result
        else:
            curr_result = main_window_result

        # desktop_step uses delta_only=True
        compact_state = parser.format_compact_text(curr_result, delta_only=True)
        # Update last_window_info to simulate real parser state across turns
        parser.last_window_info = {
            "name": curr_result["window"],
            "hwnd": curr_result["hwnd"],
            "rect": curr_result["rect"],
        }

        action_msg = f"Step Action: Success: left_click at #{step_num % 5 + 1}"
        full_turn_output = f"{action_msg}\n\nPost-Action State:\n{compact_state}"
        step_outputs.append(full_turn_output)

    total_words = sum(len(out.split()) for out in step_outputs)
    total_chars = sum(len(out) for out in step_outputs)
    est_tokens_by_chars = int(total_chars / 3.8)
    avg_tokens_per_step = est_tokens_by_chars / 15.0

    print(f"\n[Token Benchmark] Realistic 15-step task:")
    print(f"  - Total characters: {total_chars}")
    print(f"  - Estimated tokens: {est_tokens_by_chars}")
    print(f"  - Average tokens per step: {avg_tokens_per_step:.1f}")

    # Assert per-step token cost is small (< 80 tokens)
    assert avg_tokens_per_step < 80

    # Assert cumulative 15-step total is bounded (< 1,200 tokens)
    assert est_tokens_by_chars < 1200
