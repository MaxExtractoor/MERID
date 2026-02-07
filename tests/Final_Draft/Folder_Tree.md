C:/dev/merid/
├─ .env                        # Secrets (never committed)
├─ .gitignore
├─ README.md                   # High-level orientation
├─ wiki/                       # Governance-first documentation (source of truth)
│  ├─ 00-Charter/
│  ├─ 01-ADR/
│  ├─ 02-Invariants/
│  ├─ 03-Security/
│  ├─ 04-Heart/
│  ├─ 05-Eyes/
│  ├─ 06-Brain/
│  ├─ 07-Spine/
│  ├─ 08-Memory/
│  ├─ 09-Governance/
│  ├─ 10-Learning/
│  ├─ 11-Simulation/
│  ├─ 12-Optimization/
│  ├─ 13-Ports/
│  └─ 99-Archive/
│
├─ src/
│  └─ merid/
│     ├─ __init__.py            # Declares MERID as a bounded system
│     │
│     ├─ eyes/                  # Inputs, perception, ingestion
│     │  ├─ __init__.py
│     │  └─ README.md
│     │
│     ├─ brain/                 # Reasoning, attention, reflection
│     │  ├─ __init__.py
│     │  └─ README.md
│     │
│     ├─ spine/                 # Message bus, routing, enforcement
│     │  ├─ __init__.py
│     │  └─ README.md
│     │
│     ├─ memory/                # Heart: memory layers, EKG, ledger
│     │  ├─ __init__.py
│     │  └─ README.md
│     │
│     ├─ learning/              # Intuition, schooling, self-supervised loops
│     │  ├─ __init__.py
│     │  └─ README.md
│     │
│     ├─ simulation/            # Multiverse, scenario testing
│     │  ├─ __init__.py
│     │  └─ README.md
│     │
│     ├─ optimization/          # Classical + quantum candidate generators
│     │  ├─ __init__.py
│     │  └─ README.md
│     │
│     ├─ ports/                 # External interfaces (tools, quantum, APIs)
│     │  ├─ __init__.py
│     │  └─ README.md
│     │
│     ├─ security/              # Secrets handling, integrity, SLP-1
│     │  ├─ __init__.py
│     │  └─ README.md
│     │
│     ├─ governance/            # Council interface, explain-or-abstain
│     │  ├─ __init__.py
│     │  └─ README.md
│     │
│     └─ utils/                 # Pure helpers (no authority, no state)
│        ├─ __init__.py
│        └─ README.md
│
└─ tests/                       # Empty for now — future harness
   └─ README.md
