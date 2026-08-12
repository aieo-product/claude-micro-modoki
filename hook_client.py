import sys
import json
import traceback
import requests

bridge_addr = '127.0.0.1'
bridge_port = 35703

claude_input = "\n".join(sys.stdin.readlines())

with open("claudecode.log", "a", encoding="utf-8") as f:
    f.write(claude_input)

claude_input = json.loads(claude_input)

try:
    req = requests.post(f"http://{bridge_addr}:{bridge_port}/decision", json=claude_input, timeout=240)

except ConnectionRefusedError:
    with open("claudecode.log", "a", encoding="utf-8") as f:
        f.write("\n" + "Connection Refused" + "\n")
    exit(-2)

except Exception as error:
    errortext = traceback.format_exc()
    with open("claudecode.log", "a", encoding="utf-8") as f:
        f.write("\n" + errortext + "\n")
    exit(-1)

if not req.ok:
    exit(-1)

else:
    resp = req.json()
    result = resp.get("result")

    if result == 'accept':
        permission_decision = "allow"
        reason = "approved by bridge"
    elif result == 'fallback':
        permission_decision = "ask"
        reason = "held by bridge, falling back to manual approval"
    elif result == 'deny':
        permission_decision = "deny"
        reason = "denied by bridge"
    else:
        # 'timeout' or anything unrecognized: fail closed.
        permission_decision = "deny"
        reason = f"denied by bridge (result={result})"

    s = json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": permission_decision,
            "permissionDecisionReason": reason
        }
    })

    print(s)
    exit(0)
