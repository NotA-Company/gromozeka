# Divination: Unknown Layout Discovery

## Overview
Add support for discovering unknown divination layouts (Tarot and Runes) using LLM with web search capability, then reuse saved layouts from the database.

## Core Requirements
- Support both Tarot and Runes systems
- Reuse existing web search tool (no creation needed)
- Both slash commands and LLM tools should use the discovery flow
- Update LLM tool parameter documentation to mention custom layouts
- Update relevant documentation
- Write comprehensive tests

## Implementation Plan

### Database Repository
- Review and understand the actual DivinationLayoutsRepository API
- Use correct repository methods (avoid incorrect method assumptions)
- Fix repository to use provider.upsert() instead of current SQL approach for better portability

### Divination Handler Updates
- Update the existing divination handler to support unknown layout discovery
- Implement the approved flow logic: check DB → discover with tools enabled → structure result → save to DB → return
- Follow existing handler patterns for LLMService interaction
- Apply correct ChatSettings usage patterns

### LLM Tool Integration
- Update LLM tool parameters to document custom layout support
- Ensure both slash commands and LLM function paths use the same discovery mechanism

### Configuration Management
- Study existing prompt management patterns in the project
- Add new prompts following established configuration practices

## Discovery Flow
1. Query database for existing layout
2. If not found, request layout information from LLM with tools enabled
3. Request structured layout version from LLM (separate call)
4. Save layout to database (whether structured version exists or not)
5. Return the layout if structured, or None if not structured

## Order of Operations
1. Review and understand repository API
2. Update divination handler with discovery flow
3. Update configuration with new prompts
4. Update LLM tool parameters documentation
5. Write tests for discovery flow
6. Update relevant project documentation
