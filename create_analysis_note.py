import os
import glob
from datetime import datetime, timezone

skills_dir = "/Users/c/wiki/aistudio-skills/skills/system_skills"
output_file = "/Users/c/wiki/raw/aistudio-skills-analysis.md"

skill_files = glob.glob(os.path.join(skills_dir, "*/SKILL.md"))

content = f"""---
title: "AI Studio Skills Analysis"
source: "local-aistudio-skills"
created: {datetime.now(timezone.utc).astimezone().isoformat()}
tags: [task/report]
status: pending
---

# AI Studio Skills Collection
Below are the definitions and instructions for the AI Studio skills. Please analyze them and provide a comprehensive report on their capabilities, architecture, and purpose.

"""

for f in skill_files:
    with open(f, "r") as file:
        content += f"## {os.path.basename(os.path.dirname(f))}\\n\\n"
        content += file.read() + "\\n\\n"

with open(output_file, "w") as out:
    out.write(content)

print(f"Created {output_file}")
