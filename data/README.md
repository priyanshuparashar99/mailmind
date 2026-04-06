# Sample Data for MailMind

This folder contains sample rules and knowledge base material for the MailMind email processing system.

## Structure

```
data/
├── README.md          # This file
├── rules.json         # Sample email routing rules
└── kb/                # Knowledge base documents for RAG
    ├── support-faq.md
    ├── invoice-procedures.md
    ├── company-policies.md
    ├── troubleshooting.md
    └── meeting-scheduling.md
```

## Rules (rules.json)

Contains 9 sample rules covering different email intents and action types:

### Rule Categories

1. **Alert Escalation**: Critical or urgent alerts routed to admin
2. **Invoice Processing**: High and standard priority invoice routing with escalation
3. **Support Responses**: Auto-reply with KB context or HITL escalation for high urgency
4. **Meeting Requests**: Calendar routing with optional HITL for urgent meetings
5. **General**: Default routing for unclassified emails
6. **Spam**: Auto-labeling detected spam

### Rule Fields

Each rule includes:

- `name` - Rule identifier
- `description` - Human-readable purpose
- `intent_match` - Email intent to match (`invoice`, `urgent_alert`, `support_query`, `meeting_request`, `spam`, `general`)
- `urgency_min` - Minimum urgency threshold (0-10)
- `action_type` - Action to take (`label`, `reply`, `forward`, `escalate`)
- `action_value` - Parameter for action (email address, label name, etc)
- `require_hitl` - Whether to require human approval before executing

### Seeding Rules

To seed these rules into the database:

```bash
python backend/seed.py
```

This will load rules from `data/rules.json` and insert them into PostgreSQL.

## Knowledge Base (kb/)

Contains 5 markdown documents covering company operations and procedures. These files are indexed by the RAG system and used to generate contextual replies.

### KB Documents

1. **support-faq.md** (1,500+ words)
   - Account & billing FAQs
   - Technical support troubleshooting
   - Data & security information
   - Used to auto-respond to support queries

2. **invoice-procedures.md** (1,200+ words)
   - Invoice workflow and approval process
   - Content requirements
   - Special cases (recurring, disputed, partial invoices)
   - Tax compliance guidelines
   - Used as context for finance team replies

3. **company-policies.md** (1,400+ words)
   - Communication standards and email etiquette
   - Data protection & privacy guidelines
   - Meeting & calendar management
   - Vendor management procedures
   - Performance expectations
   - Used for general policy inquiries

4. **troubleshooting.md** (1,600+ words)
   - Login and account access issues
   - Data sync problems
   - Performance troubleshooting
   - API integration issues
   - Browser compatibility
   - Support escalation guidelines
   - Used for technical issue resolution

5. **meeting-scheduling.md** (1,400+ words)
   - Meeting request guidelines
   - Calendar best practices
   - Virtual meeting etiquette
   - Conference room logistics
   - Timezone coordination
   - Used for meeting request replies

### Indexing KB

To build the FAISS index for RAG:

```bash
python -c "from backend.services.rag import build_index; build_index('data/kb')"
```

This chunks documents, generates embeddings, and saves to `backend/faiss_index/`.

## Usage in Email Processing

### 1. Rule-Based Routing

When an email arrives:

1. Classifier determines intent and urgency
2. Rule engine matches against rules in order
3. Action executed (forward, label, escalate, reply)
4. If HITL required, item queued for human approval

### 2. RAG-Powered Replies

For `reply` action type:

1. Email content queried against KB index
2. Top 3 matching documents retrieved
3. Groq LLM generates contextual reply using retrieved context
4. Reply sent via Resend API

## Customizing

### Adding New Rules

Edit `data/rules.json` and add a new rule object:

```json
{
  "name": "Your Rule Name",
  "description": "Rule description",
  "intent_match": "invoice",
  "urgency_min": 5,
  "action_type": "forward",
  "action_value": "team@company.com",
  "require_hitl": false
}
```

Then seed:

```bash
python backend/seed.py
```

### Adding KB Documents

1. Create new markdown file in `kb/` folder
2. Write content in markdown format (headers, bullet points, etc)
3. Rebuild index:

```bash
python -c "from backend.services.rag import build_index; build_index('data/kb')"
```

### Modifying KB Documents

Edit existing markdown files in `kb/` and rebuild index when done:

```bash
python -c "from backend.services.rag import build_index; build_index('data/kb')"
```

## Performance Notes

- **Rules**: Evaluated in order; first match wins. ~5ms per rule evaluation
- **KB Retrieval**: FAISS similarity search typically returns results in <100ms
- **Context Window**: Retrieved KB context limited to 512 tokens max to keep API calls efficient
- **Chunking**: Documents split into 500-word chunks with 50-word overlap for better retrieval

## Testing the Pipeline

You can manually test the email processing:

```bash
cd backend

# Activate virtual environment
source .venv/bin/activate  # On Windows: .venv\Scripts\Activate.ps1

# Test classification with a sample email
python -c "
from agent.state import EmailInput
from api.logs import get_logs
input = EmailInput(email_id='test-123', from_addr='customer@example.com', subject='Test', body='Help!')
# Manual graph invocation would go here
"
```

Or use the webhook endpoint to test with actual Resend email events.

## Next Steps

1. Customize rules for your organization
2. Add/update KB documents with your company's procedures
3. Seed rules: `python backend/seed.py`
4. Build KB index: `python -c "from backend.services.rag import build_index; build_index('data/kb')"`
5. Start the system: `docker-compose up`
6. Test via email or dashboard
