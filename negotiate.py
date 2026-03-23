"""
Negotiation questionnaire handler and addendum PDF builder.
Imported by app.py.
"""
import json
import os
import tempfile
import anthropic
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_CENTER

NAVY   = colors.HexColor("#14285A")
NEG    = colors.HexColor("#2C5F2E")
BGNEG  = colors.HexColor("#F0FAF0")
LB     = colors.HexColor("#3A6EA5")
MG     = colors.HexColor("#6B7280")
DG     = colors.HexColor("#1F2937")
LG     = colors.HexColor("#F0F2F5")
RULE   = colors.HexColor("#CBD5E1")
WHITE  = colors.white
T1     = colors.HexColor("#C0392B")
T2     = colors.HexColor("#D4860B")

PW, PH = letter
M  = 0.55 * inch
CW = PW - 2 * M


def mk_styles():
    b = dict(fontName="Helvetica", fontSize=8, leading=11.5, textColor=DG)
    def s(n, **k): return ParagraphStyle(n, **{**b, **k})
    return {
        'sh':   s('sh',  fontName='Helvetica-Bold', fontSize=9.5, textColor=WHITE, leading=12),
        'ss':   s('ss',  fontSize=7, textColor=WHITE, leading=9),
        'ch':   s('ch',  fontName='Helvetica-Bold', fontSize=7.5, textColor=WHITE, leading=10),
        'cb':   s('cb',  fontName='Helvetica-Bold', fontSize=7.5, leading=10),
        'cv':   s('cv',  fontSize=7.5, leading=10),
        'ml':   s('ml',  fontName='Helvetica-Bold', fontSize=7.5, textColor=MG, leading=10),
        'mv':   s('mv',  fontSize=7.5, leading=10),
        'h2':   s('h2',  fontName='Helvetica-Bold', fontSize=10, textColor=NAVY, leading=13),
        'body': s('body',fontSize=8.5, leading=13),
        'bb':   s('bb',  fontName='Helvetica-Bold', fontSize=8.5, leading=13),
        'neg_h':s('neg_h',fontName='Helvetica-Bold', fontSize=9, textColor=NEG, leading=12),
        'neg_b':s('neg_b',fontSize=8, leading=12),
        'pri':  s('pri', fontName='Helvetica-Bold', fontSize=8, textColor=NEG, leading=11),
        'disc': s('disc',fontSize=6.5, textColor=MG, leading=9),
        'warn': s('warn',fontName='Helvetica-Bold', fontSize=8.5, textColor=T1, leading=12),
        'ctx_l':s('ctx_l',fontName='Helvetica-Bold', fontSize=7.5, textColor=NAVY, leading=10),
        'ctx_v':s('ctx_v',fontSize=7.5, leading=10),
    }


def on_page(logo_path):
    def draw(c, doc):
        c.saveState()
        c.setFillColor(NAVY)
        c.rect(0, PH - 0.70 * inch, PW, 0.70 * inch, fill=1, stroke=0)
        if logo_path and os.path.exists(logo_path):
            lw = 1.75 * inch
            lh = lw * (693 / 1920)
            c.drawImage(logo_path, M, PH - 0.70 * inch + (0.70 * inch - lh) / 2,
                        width=lw, height=lh, mask='auto')
        c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 8)
        c.drawRightString(PW - M, PH - 0.27 * inch, "NEGOTIATION ADDENDUM")
        c.setFont("Helvetica", 7)
        c.setFillColor(colors.HexColor("#A0AEC0"))
        c.drawRightString(PW - M, PH - 0.41 * inch,
                          "Tailored deal-specific guidance — Agent Advisory supplement")
        c.setStrokeColor(RULE); c.setLineWidth(0.4)
        c.line(M, 0.40 * inch, PW - M, 0.40 * inch)
        c.setFillColor(MG); c.setFont("Helvetica", 6.5)
        c.drawCentredString(PW / 2, 0.26 * inch,
            "Hope Home Inspections  |  Nick Linse  |  (813) 777-6265 call or text  |  Nick-L@hopehomeinspections.com")
        c.drawRightString(PW - M, 0.26 * inch, f"Page {doc.page}")
        c.restoreState()
    return draw


def hdr(title, sub, bg, ST):
    t = Table([[Paragraph(title, ST['sh'])], [Paragraph(sub, ST['ss'])]], colWidths=[CW])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    return t


def analyze_negotiation(form_data, api_key):
    """Send questionnaire answers to Claude and get structured strategy back."""
    client = anthropic.Anthropic(api_key=api_key)

    system = """You are an expert real estate negotiation advisor for Hope Home Inspections in Tampa Bay, Florida.
An agent has submitted deal-specific context about a transaction following a home inspection.
Your job is to provide a practical, specific negotiation strategy based on all the information provided.

RULES:
- Be direct and practical. Do not pad with generic advice.
- Factor in every piece of context provided. Seller motivation, days on market, offer dynamics, and agent read all matter.
- Rank negotiation items by likelihood of success given this specific deal context.
- Flag items the agent should NOT push on given the deal dynamics.
- If the seller is an investor or the home has been relisted, they are more likely to push back on credits.
- If DOM is high (60+ days), buyer has more leverage. If DOM is low (<21 days), seller has more leverage.
- If offer was at or above ask, credit requests need stronger justification.
- If offer was significantly below ask, seller may feel they already gave on price.
- Tone: direct, plain language, no corporate speak. Like advice from a trusted expert colleague.

OUTPUT FORMAT — return ONLY valid JSON, no markdown:
{
  "deal_summary": "2-3 sentence plain-language summary of the deal dynamics and overall leverage position",
  "leverage_assessment": "Buyer-favorable | Neutral | Seller-favorable",
  "leverage_explanation": "One sentence explaining why",
  "priority_strategy": [
    {
      "rank": 1,
      "item": "item name",
      "approach": "repair addendum or credit request",
      "amount": "$ amount if credit, or blank if repair",
      "reasoning": "why this item, why this approach, given this specific deal",
      "success_likelihood": "High | Moderate | Low"
    }
  ],
  "items_to_drop": [
    {
      "item": "item name",
      "reason": "why not to push on this given the deal context"
    }
  ],
  "opening_vs_final": "Brief guidance on whether to open with everything or sequence the ask",
  "watch_out": "One key risk or thing the agent should be aware of in this negotiation",
  "total_ask_recommendation": "Recommended total credit ask amount with brief rationale"
}"""

    # Parse item selections if provided
    item_selections_raw = form_data.get('item_selections', '{}')
    try:
        item_selections = json.loads(item_selections_raw)
    except Exception:
        item_selections = {}

    # Format selections for the prompt
    selections_text = ""
    if item_selections:
        repair_sel = [k for k,v in item_selections.items() if v == 'Repair']
        credit_sel = [k for k,v in item_selections.items() if v == 'Credit']
        neither_sel = [k for k,v in item_selections.items() if v == 'Neither']
        if repair_sel:
            selections_text += f"\nAgent wants to request REPAIR for: {', '.join(repair_sel)}"
        if credit_sel:
            selections_text += f"\nAgent wants to request CREDIT for: {', '.join(credit_sel)}"
        if neither_sel:
            selections_text += f"\nAgent has chosen NOT to pursue: {', '.join(neither_sel)}"

    user = f"""PROPERTY: {form_data.get('property_address', 'Unknown')}
INSPECTION DATE: {form_data.get('inspection_date', 'Unknown')}
AGENT: {form_data.get('agent_name', 'Unknown')} — {form_data.get('agent_company', 'Unknown')}

AGENT'S ITEM SELECTIONS:{selections_text if selections_text else ' None provided — use your best judgment based on deal context.'}

SELLER SITUATION:
- Seller type: {form_data.get('seller_type', 'Unknown')}
- Occupancy: {form_data.get('occupancy', 'Unknown')}
- Reason for selling: {form_data.get('reason_selling', 'Not provided')}
- Previously listed: {form_data.get('prev_listed', 'Unknown')}
- Seller timeline pressure: {form_data.get('timeline', 'Unknown')}

DEAL DYNAMICS:
- Days on market: {form_data.get('dom', 'Unknown')}
- List price: ${form_data.get('list_price', 'Unknown')}
- Offer price: ${form_data.get('offer_price', 'Unknown')}
- Multiple offers present: {form_data.get('multiple_offers', 'Unknown')}
- Concessions already in contract: {form_data.get('concessions', 'None noted')}

INSPECTION CONTEXT:
- Seller aware of major findings prior to inspection: {form_data.get('seller_aware', 'Unknown')}
- Previous inspection that fell through: {form_data.get('prev_inspection', 'Unknown')}
- Recently renovated or flipped: {form_data.get('flip', 'Unknown')}
- Key findings from inspection brief (agent summary): {form_data.get('key_findings', 'See inspection brief')}

AGENT READ:
- Agent assessment of seller flexibility: {form_data.get('seller_flexibility', 'Not provided')}
- Buyer risk tolerance: {form_data.get('buyer_risk', 'Not provided')}
- Any other context: {form_data.get('other_context', 'None')}

Based on all of the above, provide a specific tailored negotiation strategy. Return only valid JSON."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        system=system,
        messages=[{"role": "user", "content": user}]
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip().rstrip("```").strip()
    return json.loads(raw)


def build_addendum(form_data, strategy, logo_path, output_path):
    ST = mk_styles()
    doc = SimpleDocTemplate(output_path, pagesize=letter,
        leftMargin=M, rightMargin=M, topMargin=0.90 * inch, bottomMargin=0.60 * inch,
        title=f"Negotiation Addendum — {form_data.get('property_address', '')}")
    story = []

    # META
    meta = [
        [Paragraph("PROPERTY", ST['ml']),
         Paragraph(form_data.get('property_address', ''), ST['mv']),
         Paragraph("PREPARED FOR", ST['ml']),
         Paragraph(form_data.get('agent_name', ''), ST['mv'])],
        [Paragraph("LEVERAGE", ST['ml']),
         Paragraph(strategy.get('leverage_assessment', ''), ST['mv']),
         Paragraph("DATE", ST['ml']),
         Paragraph(form_data.get('inspection_date', ''), ST['mv'])],
    ]
    mt = Table(meta, colWidths=[1.1 * inch, 3.0 * inch, 1.25 * inch, 1.8 * inch])
    mt.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LG),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEBELOW', (0, 0), (-1, 0), 0.4, RULE),
        ('BOX', (0, 0), (-1, -1), 0.5, RULE),
    ]))
    story.append(mt); story.append(Spacer(1, 8))

    # DEAL CONTEXT SUMMARY
    story.append(KeepTogether([
        hdr("DEAL CONTEXT SUMMARY",
            "How your deal dynamics shape the negotiation approach.", LB, ST),
        Spacer(1, 7)
    ]))

    # Context table
    ctx_data = [
        [Paragraph("Seller Type", ST['ctx_l']),
         Paragraph(form_data.get('seller_type', ''), ST['ctx_v']),
         Paragraph("Days on Market", ST['ctx_l']),
         Paragraph(form_data.get('dom', ''), ST['ctx_v'])],
        [Paragraph("Occupancy", ST['ctx_l']),
         Paragraph(form_data.get('occupancy', ''), ST['ctx_v']),
         Paragraph("Previously Listed", ST['ctx_l']),
         Paragraph(form_data.get('prev_listed', ''), ST['ctx_v'])],
        [Paragraph("List Price", ST['ctx_l']),
         Paragraph(f"${form_data.get('list_price','')}", ST['ctx_v']),
         Paragraph("Offer Price", ST['ctx_l']),
         Paragraph(f"${form_data.get('offer_price','')}", ST['ctx_v'])],
        [Paragraph("Multiple Offers", ST['ctx_l']),
         Paragraph(form_data.get('multiple_offers',''), ST['ctx_v']),
         Paragraph("Seller Timeline", ST['ctx_l']),
         Paragraph(form_data.get('timeline',''), ST['ctx_v'])],
    ]
    ct = Table(ctx_data, colWidths=[1.15*inch, 2.5*inch, 1.15*inch, 2.35*inch])
    cc = [('BACKGROUND',(0,0),(-1,-1),LG),('TOPPADDING',(0,0),(-1,-1),5),
          ('BOTTOMPADDING',(0,0),(-1,-1),5),('LEFTPADDING',(0,0),(-1,-1),6),
          ('RIGHTPADDING',(0,0),(-1,-1),6),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
          ('GRID',(0,0),(-1,-1),0.35,RULE)]
    ct.setStyle(TableStyle(cc)); story.append(ct); story.append(Spacer(1, 7))

    story.append(Paragraph(strategy.get('deal_summary', ''), ST['body']))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"<b>Overall leverage:</b> {strategy.get('leverage_assessment','')} — {strategy.get('leverage_explanation','')}",
        ST['body']))
    story.append(Spacer(1, 10))

    # PRIORITY STRATEGY
    story.append(KeepTogether([
        hdr("PRIORITIZED NEGOTIATION STRATEGY",
            "Items ranked by recommended approach and likelihood of success given your deal context.", NEG, ST),
        Spacer(1, 7)
    ]))

    for item in strategy.get('priority_strategy', []):
        rank = item.get('rank', '')
        name = item.get('item', '')
        approach = item.get('approach', '')
        amount = item.get('amount', '')
        reasoning = item.get('reasoning', '')
        likelihood = item.get('success_likelihood', '')

        color_map = {'High': NEG, 'Moderate': T2, 'Low': T1}
        lcolor = color_map.get(likelihood, MG)

        lbl_style = ParagraphStyle(f'lbl_{rank}',
            fontName='Helvetica-Bold', fontSize=7.5,
            textColor=WHITE, leading=10, backColor=lcolor,
            borderPadding=(2,5,2,5))

        row = Table([[
            Paragraph(f"#{rank}", ST['pri']),
            Paragraph(f"<b>{name}</b>", ST['cb']),
            Paragraph(approach.upper(), ST['cb']),
            Paragraph(amount if amount else "", ST['cv']),
            Paragraph(likelihood, ParagraphStyle('lk',
                fontName='Helvetica-Bold', fontSize=7,
                textColor=lcolor, leading=10)),
        ]], colWidths=[0.3*inch, 2.3*inch, 1.3*inch, 0.9*inch, 0.8*inch])
        row.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1),BGNEG),
            ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),5),
            ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('LINEBELOW',(0,0),(-1,-1),0.5,RULE),
        ]))
        story.append(row)
        story.append(Paragraph(reasoning, ST['cv']))
        story.append(Spacer(1, 8))

    # TOTAL ASK
    story.append(Paragraph(
        f"<b>Recommended total ask:</b> {strategy.get('total_ask_recommendation','')}",
        ST['neg_h']))
    story.append(Spacer(1, 4))
    story.append(Paragraph(strategy.get('opening_vs_final', ''), ST['body']))
    story.append(Spacer(1, 10))

    # ITEMS TO DROP
    if strategy.get('items_to_drop'):
        story.append(KeepTogether([
            hdr("ITEMS TO DROP FROM YOUR ASK",
                "Given this deal's dynamics, pushing on these is likely to create friction without results.", T1, ST),
            Spacer(1, 7)
        ]))
        drop_rows = [[Paragraph("Item", ST['ch']), Paragraph("Why Not to Push on This", ST['ch'])]]
        for d in strategy['items_to_drop']:
            drop_rows.append([
                Paragraph(d.get('item', ''), ST['cb']),
                Paragraph(d.get('reason', ''), ST['cv'])
            ])
        dt = Table(drop_rows, colWidths=[2.2*inch, 4.95*inch])
        dc = [('BACKGROUND',(0,0),(-1,0),T1),('TOPPADDING',(0,0),(-1,-1),5),
              ('BOTTOMPADDING',(0,0),(-1,-1),5),('LEFTPADDING',(0,0),(-1,-1),6),
              ('RIGHTPADDING',(0,0),(-1,-1),6),('VALIGN',(0,0),(-1,-1),'TOP'),
              ('GRID',(0,0),(-1,-1),0.35,RULE)]
        for i in range(1, len(drop_rows)):
            dc.append(('BACKGROUND',(0,i),(-1,i),
                       colors.HexColor("#FDEDEC") if i%2==1 else WHITE))
        dt.setStyle(TableStyle(dc)); story.append(dt); story.append(Spacer(1, 10))

    # WATCH OUT
    if strategy.get('watch_out'):
        story.append(Paragraph(
            f"<b>Watch out:</b> {strategy.get('watch_out', '')}", ST['warn']))
        story.append(Spacer(1, 10))

    # CONTACT
    story.append(HRFlowable(width=CW, thickness=0.4, color=RULE))
    story.append(Spacer(1, 5))
    story.append(Paragraph(
        "Questions about the inspection findings? "
        "Reach Nick directly at <b>(813) 777-6265</b> call or text, \"\n"
        "or email Nick-L@hopehomeinspections.com. "
        "This addendum is a supplement to the Agent Advisory Brief and should be read alongside it.",
        ST['disc']))

    fn = on_page(logo_path)
    doc.build(story, onFirstPage=fn, onLaterPages=fn)
