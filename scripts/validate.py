#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate.py - collection scanner (fleet standard, exit 0 pass / 1 error / 2 warning).

Collection-repo layout: skills live in subdirectories (skills/<name>/SKILL.md)
and/or at the repo root (SKILL.md). This scanner walks the whole repo tree
(excluding .git, tests fixtures), validates every SKILL.md frontmatter
(name + description non-empty), and reports per-skill results.

Usage:
  python scripts/validate.py              # scan whole repo for SKILL.md files
  python scripts/validate.py <file>       # validate one SKILL.md-format file

Exit codes: 0 = all skills valid (>=1 found); 1 = any skill invalid;
2 = warning (no SKILL.md found on this branch, or structure warnings).
"""
import io, os, re, sys

def check_frontmatter(path):
    """Return (errors, warnings) for one SKILL.md file."""
    errors, warnings = [], []
    try:
        text = io.open(path, encoding='utf-8', errors='replace').read()
    except OSError as e:
        return ['unreadable: %s' % e], warnings
    parts = text.split('---')
    if len(parts) < 3 or parts[0].strip():
        return ['frontmatter missing or malformed'], warnings
    head = parts[1]
    if not re.search(r'(?m)^name:\s*\S', head):
        errors.append('frontmatter missing name')
    if not re.search(r'(?m)^description:\s*\S', head):
        errors.append('frontmatter missing description')
    return errors, warnings

def main():
    args = sys.argv[1:]
    if args:
        errors, warnings = check_frontmatter(args[0])
        if errors:
            print('FAIL ' + args[0] + ': ' + '; '.join(errors))
            return 1
        print('PASS ' + args[0] + ': frontmatter ok')
        return 0
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    skills = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ('.git', '.harness', 'node_modules')]
        for fn in filenames:
            if fn == 'SKILL.md':
                skills.append(os.path.join(dirpath, fn))
    skills.sort()
    if not skills:
        print('WARN: no SKILL.md found under %s (branch-as-skill repo? checkout a skill branch)' % os.path.basename(root))
        return 2
    bad = []
    for s in skills:
        e, _ = check_frontmatter(s)
        rel = os.path.relpath(s, root)
        if e:
            bad.append('%s: %s' % (rel, '; '.join(e)))
            print('FAIL ' + rel + ': ' + '; '.join(e))
        else:
            print('ok   ' + rel)
    if bad:
        print('FAIL: %d/%d skills invalid' % (len(bad), len(skills)))
        return 1
    print('PASS: %d skills, all frontmatter valid' % len(skills))
    return 0

if __name__ == '__main__':
    sys.exit(main())
