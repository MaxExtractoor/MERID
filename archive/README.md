# MERID Archive Directory

This directory contains archived/deprecated code that is no longer used in the active MERID system.

## Purpose
- **Preserve history** - Keep old code for reference without cluttering active codebase
- **Safe cleanup** - Move unused code here instead of deleting
- **Clear separation** - Distinguish between active and archived components

## Contents
- `web/` - Old web templates and APIs
- `core/` - Deprecated core modules
- `agents/` - Old agent implementations
- `ui/` - Legacy UI components
- `docs/` - Outdated documentation

## Rule
**Nothing in this directory is used by the active MERID runtime.**
If you need code from here, move it back to the active tree and update imports.
