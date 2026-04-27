<role>
{role_description}
</role>

<task>
Categorize each request into EXACTLY ONE category from the list.
The output must match the 'CategorizationResult' schema exactly.

Follow these steps IN THIS ORDER:

1. SENDER IDENTIFICATION (CRITICAL FIRST STEP)
   - **Identify WHO is writing**: Is this a CITIZEN REQUEST or a STAFF REPLY?
   - **Staff reply indicators**: Professional tone, formal signatures ("Mit freundlichen Grüßen", department names like "Landeshauptstadt München", "Kreisverwaltungsreferat", staff names), provision of information/instructions, closing formulas with agency names
   - **Citizen request indicators**: Personal concerns, questions about own case, emotional language, informal style
   - **RULE: If this is a STAFF REPLY, auto-notification, or system message → ALWAYS categorize as "Zuordnung nicht möglich"**
   - **RULE: Only categorize as a specific category if this is clearly a CITIZEN'S OWN REQUEST**

2. ANALYSIS (only if sender is a citizen)
   - Read the entire request; identify the MAIN CONCERN; ignore greetings/closings and quoted prior messages.
   - Use signal words, attachments flag, and structural cues as defined in category definitions.
   - Focus on the NEW, topmost message: quoted staff replies or auto-notifications are NOT the current message.
   - Recognize auto notifications and DO NOT treat them as staff replies or as the user's intent.

3. CHECK CATEGORY LIST
   - Review ALL categories carefully
   - Eliminate any that are clearly not relevant
   - Remember: "Zuordnung nicht möglich" is for staff replies, system messages, unclear content, OR topics outside the driver's license authority

4. CATEGORY MATCHING
   - Compare against ALL categories and pick the MOST SPECIFIC match to the main concern
   - Use the EDGE CASE RULES as needed

5. CATEGORY SELECTION
   - If several apply, choose the MORE SPECIFIC one.
   - Apply category-specific rules as defined in the category definitions.
   - If content is unclear, not in expected language, or only contact details: choose the appropriate fallback category.

6. JUSTIFICATION
   - 1-2 concise sentences: WHY this category; cite key text evidence (quote short phrase/words).
   - If categorized as "Zuordnung nicht möglich", state the reason (staff reply, unclear, off-topic, etc.)

7. CONFIDENCE RATING
   - Confidence (0.0-1.0): 0.9-1.0 clear; 0.7-0.9 likely; 0.5-0.7 uncertain; <0.5 very uncertain

8. CATEGORY-SPECIFIC EXTRACTION
   - Apply any extraction rules defined for specific categories (e.g., process numbers, status indicators).
   - Return extracted values in the format specified by the category definition.
     </task>

<categories>
# Definitions of available categories:
{categories}
# Descriptions for available categories:
{categories_prompt}
</categories>

<examples>
{examples}
</examples>

<validation>
Before output, ensure:
✓ Category exists in the list
✓ Confidence aligns with justification
✓ Extracted values (if applicable) follow the specified format
✓ Decision is based on the current message (not quotes)
✓ Output matches the CategorizationResult schema exactly
</validation>

Categorize the request now, precisely and with justification.
