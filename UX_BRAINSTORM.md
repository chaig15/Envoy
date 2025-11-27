# UX Brainstorm: Commands vs LLM Integration

## Current Problems

1. **Two separate systems** - Users can't seamlessly switch between structured flows and natural language
2. **Mid-flow confusion** - User starts `/snipe`, types natural language, gets error instead of LLM help
3. **Duplicate functionality** - Both systems can create watches/snipes, but differently
4. **No graceful degradation** - If LLM fails, no fallback to structured flow

## User Mental Models

### Power Users (Know the System)
- Prefer commands for speed: `/snipe` → click buttons → done
- Know exactly what they want
- Want structured confirmation

### Casual Users (Don't Know Commands)
- Prefer natural language: "Get me Carbone for 2 on Dec 15"
- Don't want to learn commands
- Want conversational flow

### Mixed Users (Know Some Commands)
- Use `/search` to browse, then natural language to create
- Switch between modes based on context
- Want flexibility

## Design Options

### Option 1: LLM-First with Structured Fallback
**Approach:** LLM is primary, structured flows are fallback/confirmation
- User types natural language → LLM processes
- If LLM needs clarification → show structured buttons
- If LLM succeeds → show structured confirmation with edit options

**Pros:**
- Single entry point (natural language)
- Can still use structured UI when needed
- Feels more conversational

**Cons:**
- Commands become secondary
- Power users lose speed of buttons
- More complex to implement

### Option 2: Hybrid - Smart Routing
**Approach:** Detect intent, route to best handler
- Natural language → LLM processes
- Commands → Structured flows
- Mid-flow natural language → LLM helps complete the flow

**Example:**
- User: `/snipe` → structured flow starts
- User: "actually make it for 4 people" → LLM updates the snipe
- User: "get me carbone for 2" → LLM creates snipe directly

**Pros:**
- Best of both worlds
- Users can switch modes
- Commands stay fast for power users

**Cons:**
- More complex state management
- Need to handle context switching

### Option 3: Structured-First with LLM Enhancement
**Approach:** Commands are primary, LLM enhances them
- `/snipe` → structured flow
- But accept natural language in each step
- LLM parses natural language → fills structured form

**Example:**
- User: `/snipe`
- Bot: "What restaurant?"
- User: "Carbone for 2 on Dec 15" → LLM extracts: venue=Carbone, party=2, date=Dec 15
- Bot: Shows confirmation with buttons

**Pros:**
- Keeps structured flows
- Adds natural language parsing
- Familiar UX for command users

**Cons:**
- Still requires commands
- Less conversational

### Option 4: Unified Conversational Flow
**Approach:** Everything goes through LLM, but LLM uses structured UI when appropriate
- User: "Get me Carbone" → LLM searches, shows results with buttons
- User: "The first one" → LLM continues conversation
- User: "For 2 on Dec 15" → LLM creates snipe, shows confirmation

**Pros:**
- Single mental model
- Most flexible
- Feels most natural

**Cons:**
- Commands become aliases, not primary
- Power users might feel slower
- Requires good LLM reliability

## Recommendation: Option 2 (Hybrid - Smart Routing)

### Implementation Strategy

1. **Natural Language → LLM**
   - User types freely → LLM processes
   - LLM can create watches/snipes directly
   - LLM shows structured confirmations

2. **Commands → Structured Flows**
   - `/snipe`, `/watch` → multi-step with buttons
   - Fast for power users
   - Clear, predictable

3. **Mid-Flow Natural Language**
   - If in structured flow → LLM helps complete it
   - Parse natural language → update flow state
   - Example: User in `/snipe` flow types "make it 4 people" → update party size

4. **Graceful Transitions**
   - LLM can suggest: "Want to use `/snipe` for faster setup?"
   - Commands can suggest: "Or just tell me what you want!"
   - User can switch anytime

### Key Features

**Smart Context Detection:**
- If in structured flow → LLM enhances it
- If not → LLM handles independently
- User can always say "cancel" or "start over"

**Unified Confirmation:**
- Both paths show same confirmation format
- Both allow editing via natural language or buttons
- Consistent UX regardless of entry point

**Progressive Disclosure:**
- New users: Natural language (easier)
- Power users: Commands (faster)
- Everyone: Can switch modes

## Implementation Details

### State Management
- Track: "user is in structured flow" vs "user is in LLM conversation"
- Allow: Switching between modes
- Handle: Context preservation when switching

### LLM Enhancements
- Parse natural language in structured flows
- Extract: dates, party sizes, preferences
- Update: Flow state based on parsed input

### Command Enhancements
- Add natural language parsing to each step
- Example: `/snipe` → "What restaurant?" → User: "Carbone for 2 on Dec 15" → Extract all at once

### UX Patterns
- **Confirmation Cards:** Show structured summary after LLM creates something
- **Quick Actions:** Buttons to edit/confirm after LLM action
- **Context Awareness:** LLM knows if user is mid-flow

## Questions to Answer

1. **Should commands be shortcuts or full flows?**
   - Shortcuts: `/snipe` → LLM asks questions
   - Full flows: `/snipe` → Structured multi-step

2. **Can LLM interrupt structured flows?**
   - Yes: User types natural language → LLM helps
   - No: Structured flows are "locked in"

3. **Should we deprecate commands?**
   - Keep: Power users need them
   - Remove: Simplify to just LLM

4. **How to handle ambiguity?**
   - LLM: Ask clarifying questions
   - Commands: Show buttons/options

5. **What about `/search`?**
   - Keep as command (fast, visual)
   - Or: LLM can search too, show results

## Next Steps

1. **User Testing:** Test with real users - which do they prefer?
2. **Prototype:** Build hybrid system, test switching
3. **Iterate:** Based on feedback, refine approach
4. **Document:** Clear UX guidelines for when to use what

