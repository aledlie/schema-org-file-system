from prompt import *
import argparse
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
import json
import os
import random
import threading
import re

# Scorer API configuration from environment variables
_scorer_urls_str = os.getenv("SCORER_URLS", "YOUR_SCORER_URL")
_scorer_api_key = os.getenv("SCORER_API_KEY", "YOUR_API_KEY")
model_name = os.getenv("SCORER_MODEL_NAME", "YOUR_SCORER_MODEL_NAME")
url_list = [url.strip() for url in _scorer_urls_str.split(",") if url.strip()]
scorer_client_list = [OpenAI(api_key=_scorer_api_key, base_url=url) for url in url_list]

_LABEL_RE = re.compile(r"^\s*([AB])\b")
_TOOL_CALL_MARK = "<|start|>functions."
_RERUN_PREFIX = "🔁"

def count_tool_calls(item: dict) -> int:
    """
    Prefer explicit `tool_calls` field if present; otherwise count in `full_traj`.
    Falls back to 0 if unavailable.
    """
    if not isinstance(item, dict):
        return 0
    tc = item.get("tool_calls")
    if isinstance(tc, int) and tc >= 0:
        return tc
    full_traj = item.get("full_traj")
    if isinstance(full_traj, str) and full_traj:
        return full_traj.count(_TOOL_CALL_MARK)
    return 0


def get_llm_response(messages):
    scorer_client = random.choice(scorer_client_list)
    response = scorer_client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=0.0,
        stream=False,
        extra_body={"skip_special_tokens": False},
    )
    response = response.choices[0].message.content
    response = response.split("<|message|>")[-1].split("<|return|>")[0].strip()
    return response


def parse_judge_label(raw: str):
    """
    Expect judge to output a single label: A or B.
    Return:
      - 1 for A (correct)
      - 0 for B (wrong)
      - None for unknown (malformed output)
    """
    if raw is None:
        return None
    s = str(raw).strip()

    # First try: check if it starts with a single A/B character
    m = _LABEL_RE.match(s)
    if m:
        lab = m.group(1)
        print(lab)
        if lab == "A":
            return 1
        if lab == "B":
            return 0

    # Second try: extract content after </think> tag
    if "</think>" in s:
        after_tag = s.split("</think>", 1)[-1].strip()
        m = _LABEL_RE.match(after_tag)
        if m:
            lab = m.group(1)
            print(lab)
            if lab == "A":
                return 1
            if lab == "B":
                return 0

    return None


def _is_clean_01(x) -> bool:
    """
    True iff x is a clean 0/1 numeric label.
    - int: 0 or 1
    - float: exactly 0.0 or 1.0 (tolerate tiny fp error)
    Note: bool is excluded (since bool is subclass of int).
    """
    if isinstance(x, bool):
        return False
    if isinstance(x, int):
        return x in (0, 1)
    if isinstance(x, float):
        xi = int(x)
        return xi in (0, 1) and abs(x - xi) < 1e-9
    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_path", type=str, required=True)
    parser.add_argument("--max_workers", type=int, default=20)
    parser.add_argument("--limit", type=int, default=-1, help="Run at most N questions.")
    parser.add_argument(
        "--top_k",
        type=int,
        default=-1,
        help="Only compute metrics on the first top_k QAs in the original data order. -1 means all.",
    )
    parser.add_argument(
        "--retry_unknown",
        action="store_true",
        help="(Deprecated) Unknown items are always re-evaluated now. This flag is kept for backward compatibility.",
    )
    parser.add_argument(
        "--retry_unknown_last_n",
        type=int,
        default=-1,
        help="(Deprecated) All unknown items are always re-evaluated. This flag is kept for backward compatibility.",
    )

    args = parser.parse_args()

    save_path = args.data_path.replace(".jsonl", "_eval.jsonl")
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    with open(args.data_path, "r") as f:
        data_lines = f.readlines()
    all_data = [json.loads(line) for line in data_lines]
    data = list(all_data)
    if args.limit > 0:
        data = data[:args.limit]

   
    item_idx2scored = {}  # item_index -> item(with score)
    if os.path.exists(save_path):
        with open(save_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict) and obj.get("type") == "summary":
                    continue
                item_idx = obj.get("item_index")
                if item_idx is not None:
                    item_idx2scored[item_idx] = obj

    before = len(data)

    need_missing = []
    need_unknown = []

    for idx, item in enumerate(data):
        prev = item_idx2scored.get(idx)
        if prev is None:
            need_missing.append((idx, item))
            continue
        prev_score = prev.get("score", None)
        if not _is_clean_01(prev_score):
            need_unknown.append((idx, item))

    data_to_eval = need_missing + need_unknown

    print(
        f"[eval] loaded={before}, already_scored={len(item_idx2scored)}, "
        f"to_eval={len(data_to_eval)} (missing={len(need_missing)}, unknown={len(need_unknown)}), "
        f"save_path={save_path}, no_dedup=True, unknown_always_retry=True"
    )

    prompt_template = JUDGE_PROMPT_BC_en
    
    def score_one_item(item_idx, item, prompt_template, save_path):
        query = item["query"]
        answer = item["answer"]
        response = item["final_response"]

        messages = [
            {"role": "system", "content": "Judge the response objectively."},
            {
                "role": "user",
                "content": prompt_template.format(
                    question=query, correct_answer=answer, response=response
                ),
            },
        ]
        raw = get_llm_response(messages)
        label = parse_judge_label(raw)

        out = {
            "type": "item",
            "item_index": item_idx,  
            "query": query,
            "answer": answer,
            "final_response": response,
            "judge_raw": raw,
            "score": label if label is not None else raw,
        }
        out["is_correct"] = True if label == 1 else (False if label == 0 else None)
        out["tool_calls"] = count_tool_calls(item)
        return out

    # Thread-safe append to eval file
    file_lock = threading.Lock()

    def _worker(item_idx_and_item):
        item_idx, item = item_idx_and_item
        try:
            scored = score_one_item(item_idx, item, prompt_template, save_path)
        except Exception as e:
            print(f"\033[91mError: {e}\033[0m")
            scored = {
                "type": "item",
                "item_index": item_idx,
                "query": item.get("query"),
                "answer": item.get("answer"),
                "final_response": item.get("final_response"),
                "judge_raw": "EVAL_ERROR",
                "score": "EVAL_ERROR",
                "is_correct": None,
                "eval_error": True,
                "tool_calls": count_tool_calls(item),
            }

        with file_lock:
            with open(save_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(scored, ensure_ascii=False) + "\n")
        return scored

    if data_to_eval:
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            new_scored = list(
                tqdm(executor.map(_worker, data_to_eval), total=len(data_to_eval), desc="Scoring")
            )
        for obj in new_scored:
            item_idx = obj.get("item_index")
            # Only update successfully evaluated items (score is 0 or 1)
            if item_idx is not None and _is_clean_01(obj.get("score")):
                item_idx2scored[item_idx] = obj

    processed_data = []
    for idx, item in enumerate(all_data):
        scored_item = item_idx2scored.get(idx)
        if scored_item is not None:
            processed_data.append(scored_item)
        else:
            pass

    if args.top_k is not None and isinstance(args.top_k, int) and args.top_k > 0:
        processed_data = processed_data[: args.top_k]

    correct_num, wrong_num, unknown_num = 0, 0, 0
    incomplete_num, reach_max_tool_num, reach_max_token_num = 0, 0, 0
    tool_calls_all: list = []
    tool_calls_correct: list = []

    for item in processed_data:
        if isinstance(item["score"], str):
            print(item["score"])
            unknown_num += 1
        else:
            if item["score"] == 1:
                correct_num += 1
            elif item["score"] == 0:
                wrong_num += 1

        tc = item.get("tool_calls")
        if isinstance(tc, int) and tc >= 0:
            tool_calls_all.append(tc)
            if item.get("score") == 1:
                tool_calls_correct.append(tc)

        full_traj = item.get("full_traj")
        if isinstance(full_traj, str) and full_traj and (not full_traj.endswith("<|return|>")):
            incomplete_num += 1

        fr = item.get("final_response") or ""
        if isinstance(fr, str) and "I have used too many tools, so I will conclude my answer." in fr:
            reach_max_tool_num += 1
        if isinstance(fr, str) and (
            "The max context length has been reached." in fr
            or "I have used too many tokens, so I will conclude my answer." in fr
        ):
            reach_max_token_num += 1

    print(f"correct_num: {correct_num}, wrong_num: {wrong_num}, unknown_num: {unknown_num}")
    print(
        f"incomplete_num: {incomplete_num}, reach_max_tool_num: {reach_max_tool_num}, "
        f"reach_max_token_num: {reach_max_token_num}"
    )

    denom = (correct_num + wrong_num)
    acc = (correct_num / denom) if denom > 0 else 0.0
    print(f"accuracy: {acc}")

    avg_tool_calls_correct = (
        (sum(tool_calls_correct) / len(tool_calls_correct)) if tool_calls_correct else 0.0
    )
    min_tool_calls = min(tool_calls_all) if tool_calls_all else None
    max_tool_calls = max(tool_calls_all) if tool_calls_all else None

    summary = {
        "type": "summary",
        "data_path": args.data_path,
        "save_path": save_path,
        "total_items": len(processed_data),
        "correct_num": correct_num,
        "wrong_num": wrong_num,
        "unknown_num": unknown_num,
        "accuracy": acc,
        "avg_tool_calls_correct": avg_tool_calls_correct,
        "min_tool_calls": min_tool_calls,
        "max_tool_calls": max_tool_calls,
        "incomplete_num": incomplete_num,
        "reach_max_tool_num": reach_max_tool_num,
        "reach_max_token_num": reach_max_token_num,
    }

    tmp_path = save_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")
        for item in processed_data:
            # Only persist successfully evaluated items (score is 0 or 1)
            if not _is_clean_01(item.get("score")):
                continue
            if isinstance(item, dict) and item.get("type") != "item":
                item = dict(item)
                item["type"] = "item"
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    os.replace(tmp_path, save_path)
