import os
import json
import tempfile
import traceback
from flask import Flask, request, jsonify, send_file, render_template
import anthropic
import pdfplumber
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_CENTER
from PIL import Image
import numpy as np
import base64

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max upload

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ── Brand Colors ──────────────────────────────────────────────────
NAVY=colors.HexColor("#14285A"); LB=colors.HexColor("#3A6EA5")
T1=colors.HexColor("#C0392B"); T2=colors.HexColor("#D4860B"); T3=colors.HexColor("#2E7D32")
INS=colors.HexColor("#6A0DAD"); CODE=colors.HexColor("#1565C0")
NEG=colors.HexColor("#2C5F2E"); WDO=colors.HexColor("#1A5276")
BG1=colors.HexColor("#FDEDEC"); BG2=colors.HexColor("#FEF9EC"); BG3=colors.HexColor("#F1F8F1")
BGNEG=colors.HexColor("#F0FAF0")
WHITE=colors.white; LG=colors.HexColor("#F0F2F5")
MG=colors.HexColor("#6B7280"); DG=colors.HexColor("#1F2937"); RULE=colors.HexColor("#CBD5E1")
PW,PH=letter; M=0.55*inch; CW=PW-2*M

def mk_styles():
    b=dict(fontName="Helvetica",fontSize=8,leading=11.5,textColor=DG)
    def s(n,**k): return ParagraphStyle(n,**{**b,**k})
    return {
        'ml':s('ml',fontName='Helvetica-Bold',fontSize=7.5,textColor=MG,leading=10),
        'mv':s('mv',fontSize=7.5,leading=10),
        'sh':s('sh',fontName='Helvetica-Bold',fontSize=9.5,textColor=WHITE,leading=12),
        'ss':s('ss',fontSize=7,textColor=WHITE,leading=9),
        'ch':s('ch',fontName='Helvetica-Bold',fontSize=7.5,textColor=WHITE,leading=10),
        'cb':s('cb',fontName='Helvetica-Bold',fontSize=7.5,leading=10),
        'cv':s('cv',fontSize=7.5,leading=10),
        'ov':s('ov',fontSize=8.5,leading=13),
        'sl':s('sl',fontName='Helvetica-Bold',fontSize=7.5,textColor=NAVY,leading=10),
        'sv':s('sv',fontSize=7.5,leading=10),
        'il':s('il',fontName='Helvetica-Bold',fontSize=8.5,textColor=INS,leading=12),
        'ib':s('ib',fontSize=8,leading=12),
        'ti':s('ti',fontName='Helvetica-Bold',fontSize=8,textColor=NAVY,leading=12),
        'tb':s('tb',fontSize=8,leading=12),
        'nq':s('nq',fontSize=8,textColor=MG,leading=12),
        'disc':s('disc',fontSize=6.5,textColor=MG,leading=9),
        'neg_h':s('neg_h',fontName='Helvetica-Bold',fontSize=8.5,textColor=NEG,leading=12),
        'neg_b':s('neg_b',fontSize=8,leading=12),
        'ins_clean':s('ins_clean',fontName='Helvetica-Bold',fontSize=9,textColor=colors.HexColor("#2E7D32"),leading=13),
        'ins_sub':s('ins_sub',fontSize=8,leading=12),
        'ins_warn':s('ins_warn',fontName='Helvetica-Bold',fontSize=9,textColor=T1,leading=13),
        'code_l':s('code_l',fontName='Helvetica-Bold',fontSize=8.5,textColor=CODE,leading=12),
        'wdo_l':s('wdo_l',fontName='Helvetica-Bold',fontSize=8.5,textColor=WDO,leading=12),
        'wdo_clean':s('wdo_clean',fontName='Helvetica-Bold',fontSize=9,textColor=colors.HexColor("#2E7D32"),leading=13),
        'windmit_l':s('windmit_l',fontName='Helvetica-Bold',fontSize=7.5,textColor=NAVY,leading=10),
        'windmit_v':s('windmit_v',fontSize=7.5,leading=10),
    }

def get_logo_path():
    """Return path to white logo, creating it if needed."""
    logo_path = "/tmp/logo_white.png"
    src = os.path.join(os.path.dirname(__file__), "logo_white.png")
    if os.path.exists(src):
        return src
    return None

def on_page(logo_path):
    def draw(c, doc):
        c.saveState()
        c.setFillColor(NAVY); c.rect(0,PH-0.70*inch,PW,0.70*inch,fill=1,stroke=0)
        if logo_path and os.path.exists(logo_path):
            lw=1.75*inch; lh=lw*(693/1920)
            c.drawImage(logo_path,M,PH-0.70*inch+(0.70*inch-lh)/2,width=lw,height=lh,mask='auto')
        c.setFillColor(WHITE); c.setFont("Helvetica-Bold",8)
        c.drawRightString(PW-M,PH-0.27*inch,"AGENT ADVISORY")
        c.setFont("Helvetica",7); c.setFillColor(colors.HexColor("#A0AEC0"))
        c.drawRightString(PW-M,PH-0.41*inch,"Prepared for your agent to support your home buying conversation")
        c.setStrokeColor(RULE); c.setLineWidth(0.4)
        c.line(M,0.40*inch,PW-M,0.40*inch)
        c.setFillColor(MG); c.setFont("Helvetica",6.5)
        c.drawCentredString(PW/2,0.26*inch,"Hope Home Inspections  |  Office: (813) 921-8887  |  Nick direct: (813) 777-6265  |  hopehomeinspections.com")
        c.drawRightString(PW-M,0.26*inch,f"Page {doc.page}")
        c.restoreState()
    return draw

def hdr(title, sub, bg, ST):
    t=Table([[Paragraph(title,ST['sh'])],[Paragraph(sub,ST['ss'])]],colWidths=[CW])
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),bg),('TOPPADDING',(0,0),(-1,-1),5),
        ('BOTTOMPADDING',(0,0),(-1,-1),4),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8)]))
    return t

def ftable(rows, tc, bg, ST, cr=False):
    hdrs=['Finding','Plain-Language Summary','Est. Repair Range']
    cws=[1.52*inch,3.60*inch,1.02*inch]
    if cr: hdrs.append('Repair/Credit'); cws=[1.52*inch,3.10*inch,1.02*inch,0.90*inch]
    data=[[Paragraph(h,ST['ch']) for h in hdrs]]
    for r in rows:
        cells=[Paragraph(r.get('item',''),ST['cb']),
               Paragraph(r.get('sum',''),ST['cv']),
               Paragraph(r.get('rng',''),ST['cv'])]
        if cr: cells.append(Paragraph(r.get('cr',''),ST['cv']))
        data.append(cells)
    cmds=[('BACKGROUND',(0,0),(-1,0),tc),('TOPPADDING',(0,0),(-1,-1),5),
          ('BOTTOMPADDING',(0,0),(-1,-1),5),('LEFTPADDING',(0,0),(-1,-1),6),
          ('RIGHTPADDING',(0,0),(-1,-1),6),('VALIGN',(0,0),(-1,-1),'TOP'),
          ('GRID',(0,0),(-1,-1),0.35,RULE)]
    for i in range(1,len(data)): cmds.append(('BACKGROUND',(0,i),(-1,i),bg if i%2==1 else WHITE))
    t=Table(data,colWidths=cws,repeatRows=1); t.setStyle(TableStyle(cmds)); return t

def extract_pdf_text(pdf_bytes):
    """Extract text from PDF bytes using pdfplumber."""
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        f.write(pdf_bytes)
        f.flush()
        try:
            with pdfplumber.open(f.name) as pdf:
                text = ""
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        text += t + "\n"
            return text
        finally:
            os.unlink(f.name)

def analyze_with_claude(inspection_text, year_built, fourpoint_text=None,
                         windmit_text=None, wdo_text=None):
    """Send report texts to Claude API and get structured brief data back."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    system_prompt = """You are an expert home inspection analyst for Hope Home Inspections, a veteran-owned inspection company in the Tampa Bay area. Your job is to analyze inspection reports and produce structured data for an Agent Advisory Brief.

RULES — follow these exactly:

TIERING:
- Tier 1 (Safety/Structural): Active safety hazards, confirmed active moisture intrusion, broken glass, malfunctioning safety devices (smoke detectors, garage door safety), dead outlets with unknown cause, structural concerns
- Tier 2 (Functional/Mechanical): Systems not working as intended, prior dry moisture staining (not active), HVAC deficiencies, pool deficiencies, functional failures. Include Repair/Credit recommendation.
- Tier 3 (Cosmetic/Maintenance): Normal wear, cracks in driveways/walkways/stucco, caulking, paint, cosmetic ceiling cracks, minor items
- Code Advisory: Grandfathered conditions where sellers have no obligation to correct. Classic example: aluminum screen cage not grounded. Low probability, high consequence framing.

INSURANCE FLAGS (CRITICAL RULES):
- Insurance flags come ONLY from the 4-point inspection document
- If no 4-point provided: use placeholder language
- Flag ONLY items explicitly noted as deficiencies ON the 4-point, known-problem wiring types (solid strand aluminum branch wiring ONLY — multistrand is fine), known-problem panel brands (Federal Pacific, Zinsco, Pushmatic), known-problem plumbing materials (polybutylene), old roof (15+ years), old water heater (10+ years)
- Multistrand aluminum wiring for service/appliances is STANDARD and NOT a flag
- If 4-point is clean with no deficiencies: state that clearly and positively
- Do NOT import findings from the full inspection report into insurance flags

WIND MITIGATION:
- If wind mit provided: summarize the key credits (roof shape, roof covering, roof deck attachment, roof-to-wall connection, opening protection)
- Note whether the result is favorable, mixed, or unfavorable for insurance premiums
- A hip roof, hurricane straps, and impact openings = strong credits = lower premiums

WDO:
- If WDO clean: positive callout in overview
- If WDO has active infestation: Tier 1
- If WDO has conducive conditions only: Tier 2 or Tier 3
- If no WDO: note it was not completed

COST RANGES (Tampa Bay market):
- Be realistic, not worst-case. Dry moisture staining is typically cosmetic ($50-$300). 
- Minor roof vent damage: note roofer evaluation needed before repair is recommended
- Exterior maintenance bundles: $600-$1,500 combined
- Insulation gaps: $600-$1,800 depending on scope
- Do not error high on everything — practical ranges that won't kill deals

NEGOTIATION FRAMEWORK:
- Repair addendum: items where source is unknown/needs verification, safety items that need documented completion, items seller can easily do before close
- Credit request: items where seller access during contract is impractical, specialty work buyer should control, multiple small items bundled
- Informational only: low-cost items, items needing evaluation before any ask, items not worth the goodwill spent
- Calculate total credit range as sum of credit items low and high ends

PROPERTY OVERVIEW:
- Write a compliment sandwich: open with what is strong (especially roof, HVAC, water heater ages), middle with what needs attention, close with perspective
- Extract: address, agent name, agent company, agent phone/email, client name, inspection date from the report header

OUTPUT FORMAT — return ONLY valid JSON, no markdown, no preamble:
{
  "property": {
    "address": "",
    "client_name": "",
    "agent_name": "",
    "agent_company": "",
    "inspection_date": "",
    "year_built": "",
    "building_type": "",
    "foundation": "",
    "wall_construction": ""
  },
  "systems": [
    {"name": "", "detail": "", "condition": ""}
  ],
  "overview_paragraphs": ["", "", ""],
  "insurance": {
    "fourpoint_completed": true,
    "clean": true,
    "summary": "",
    "flags": [{"item": "", "detail": ""}]
  },
  "wind_mit": {
    "completed": true,
    "credits": [{"category": "", "value": "", "impact": ""}],
    "overall": ""
  },
  "wdo": {
    "completed": true,
    "clean": true,
    "summary": "",
    "findings": []
  },
  "tier1": [{"item": "", "sum": "", "rng": ""}],
  "tier2": [{"item": "", "sum": "", "rng": "", "cr": ""}],
  "tier3": [{"item": "", "sum": "", "rng": ""}],
  "code_advisory": [{"item": "", "code": "", "risk": "", "cost": "", "obligation": ""}],
  "negotiation": {
    "addendum": [{"item": "", "why": ""}],
    "credit": [{"item": "", "rng": "", "why": ""}],
    "info_only": [{"item": "", "why": ""}],
    "total_low": 0,
    "total_high": 0
  },
  "talking_points": [{"label": "", "text": ""}]
}"""

    user_parts = [f"YEAR BUILT (from order, not in report): {year_built}\n\n"]
    user_parts.append(f"FULL HOME INSPECTION REPORT:\n{inspection_text[:40000]}\n\n")

    if fourpoint_text:
        user_parts.append(f"4-POINT INSPECTION:\n{fourpoint_text[:8000]}\n\n")
    else:
        user_parts.append("4-POINT INSPECTION: Not completed for this property.\n\n")

    if windmit_text:
        user_parts.append(f"WIND MITIGATION INSPECTION:\n{windmit_text[:8000]}\n\n")
    else:
        user_parts.append("WIND MITIGATION: Not completed for this property.\n\n")

    if wdo_text:
        user_parts.append(f"WDO INSPECTION:\n{wdo_text[:5000]}\n\n")
    else:
        user_parts.append("WDO INSPECTION: Not completed for this property.\n\n")

    user_parts.append("Analyze all provided documents and return the JSON structure. Return ONLY valid JSON.")

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        system=system_prompt,
        messages=[{"role": "user", "content": "".join(user_parts)}]
    )

    raw = response.content[0].text.strip()
    # Strip any accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip().rstrip("```").strip()
    return json.loads(raw)

def build_pdf(data, logo_path, output_path):
    """Build the PDF from structured data."""
    ST = mk_styles()
    doc = SimpleDocTemplate(output_path, pagesize=letter,
        leftMargin=M, rightMargin=M, topMargin=0.90*inch, bottomMargin=0.60*inch,
        title=f"Agent Advisory — {data['property'].get('address','')}")
    story = []
    p = data['property']

    # META
    meta=[
        [Paragraph("PROPERTY",ST['ml']),    Paragraph(p.get('address',''),ST['mv']),
         Paragraph("INSPECTION DATE",ST['ml']), Paragraph(p.get('inspection_date',''),ST['mv'])],
        [Paragraph("PREPARED FOR",ST['ml']), Paragraph(f"{p.get('agent_name','')} — {p.get('agent_company','')}",ST['mv']),
         Paragraph("INSPECTOR",ST['ml']),    Paragraph("Nick Linse, Hope Home Inspections",ST['mv'])],
        [Paragraph("YEAR BUILT",ST['ml']),  Paragraph(p.get('year_built',''),ST['mv']),
         Paragraph("CONSTRUCTION",ST['ml']), Paragraph(f"{p.get('building_type','')} | {p.get('foundation','')}",ST['mv'])],
    ]
    mt=Table(meta,colWidths=[1.1*inch,3.0*inch,1.25*inch,1.8*inch])
    mt.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),LG),('TOPPADDING',(0,0),(-1,-1),5),
        ('BOTTOMPADDING',(0,0),(-1,-1),5),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LINEBELOW',(0,0),(-1,0),0.4,RULE),
        ('LINEBELOW',(0,1),(-1,1),0.4,RULE),('BOX',(0,0),(-1,-1),0.5,RULE)]))
    story.append(mt); story.append(Spacer(1,8))

    # OVERVIEW
    story.append(KeepTogether([hdr("PROPERTY OVERVIEW","Summary of overall condition and key system ages",LB,ST),Spacer(1,7)]))
    for para in data.get('overview_paragraphs', []):
        story.append(Paragraph(para, ST['ov'])); story.append(Spacer(1,5))
    story.append(Spacer(1,5))

    # Systems table
    sys_rows = [[Paragraph("SYSTEM",ST['ch']),Paragraph("DETAIL",ST['ch']),Paragraph("CONDITION",ST['ch'])]]
    for sys in data.get('systems', []):
        sys_rows.append([Paragraph(sys.get('name',''),ST['sl']),
                         Paragraph(sys.get('detail',''),ST['sv']),
                         Paragraph(sys.get('condition',''),ST['sv'])])
    sc=[('BACKGROUND',(0,0),(-1,0),NAVY),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
        ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('GRID',(0,0),(-1,-1),0.35,RULE)]
    st=Table(sys_rows,colWidths=[1.15*inch,3.5*inch,2.5*inch])
    for i in range(1,len(sys_rows)): sc.append(('BACKGROUND',(0,i),(-1,i),LG if i%2==1 else WHITE))
    st.setStyle(TableStyle(sc)); story.append(st); story.append(Spacer(1,10))

    # WDO
    wdo = data.get('wdo', {})
    if wdo.get('completed'):
        story.append(KeepTogether([hdr("WDO INSPECTION","Wood Destroying Organism inspection results.",WDO,ST),Spacer(1,7)]))
        if wdo.get('clean'):
            story.append(Paragraph("WDO Inspection: No Active Infestation or Damage Found", ST['wdo_clean']))
        else:
            story.append(Paragraph("WDO Inspection: Findings Present", ST['ins_warn']))
        story.append(Spacer(1,4))
        story.append(Paragraph(wdo.get('summary',''), ST['ins_sub']))
        if wdo.get('findings'):
            for f in wdo['findings']:
                story.append(Paragraph(f"• {f}", ST['ib']))
        story.append(Spacer(1,10))

    # INSURANCE FLAGS
    ins = data.get('insurance', {})
    story.append(KeepTogether([hdr("INSURANCE FLAGS","Based on the completed 4-point inspection for this property.",INS,ST),Spacer(1,7)]))
    if not ins.get('fourpoint_completed'):
        story.append(Paragraph("4-Point Inspection: Not Completed", ST['ins_warn']))
        story.append(Spacer(1,4))
        story.append(Paragraph("A 4-point inspection was not completed for this property. Insurability implications of the findings above have not been evaluated. The buyer should consult with their insurance agent prior to closing regarding coverability of this property.", ST['ins_sub']))
    elif ins.get('clean') and not ins.get('flags'):
        story.append(Paragraph("4-Point Inspection: No Deficiencies Noted", ST['ins_clean']))
        story.append(Spacer(1,4))
        story.append(Paragraph(ins.get('summary',''), ST['ins_sub']))
    else:
        story.append(Paragraph("4-Point Inspection: Deficiencies or Flags Present", ST['ins_warn']))
        story.append(Spacer(1,4))
        story.append(Paragraph(ins.get('summary',''), ST['ins_sub']))
        for flag in ins.get('flags', []):
            story.append(Spacer(1,5))
            story.append(Paragraph(flag.get('item',''), ST['il']))
            story.append(Paragraph(flag.get('detail',''), ST['ib']))

    # WIND MIT
    windmit = data.get('wind_mit', {})
    if windmit.get('completed'):
        story.append(Spacer(1,8))
        story.append(KeepTogether([hdr("WIND MITIGATION SUMMARY","Key credits that affect the buyer's homeowners insurance premium.",NAVY,ST),Spacer(1,7)]))
        wm_rows=[[Paragraph("CATEGORY",ST['ch']),Paragraph("RESULT",ST['ch']),Paragraph("PREMIUM IMPACT",ST['ch'])]]
        for cr in windmit.get('credits',[]):
            wm_rows.append([Paragraph(cr.get('category',''),ST['windmit_l']),
                            Paragraph(cr.get('value',''),ST['windmit_v']),
                            Paragraph(cr.get('impact',''),ST['windmit_v'])])
        wmt=Table(wm_rows,colWidths=[1.8*inch,2.8*inch,2.55*inch])
        wmc=[('BACKGROUND',(0,0),(-1,0),NAVY),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
             ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('VALIGN',(0,0),(-1,-1),'TOP'),
             ('GRID',(0,0),(-1,-1),0.35,RULE)]
        for i in range(1,len(wm_rows)): wmc.append(('BACKGROUND',(0,i),(-1,i),LG if i%2==1 else WHITE))
        wmt.setStyle(TableStyle(wmc)); story.append(wmt); story.append(Spacer(1,5))
        story.append(Paragraph(windmit.get('overall',''), ST['ins_sub']))
    story.append(Spacer(1,10))

    # TIERS
    if data.get('tier1'):
        story.append(KeepTogether([hdr("TIER 1: SAFETY AND STRUCTURAL","Address regardless of negotiation outcome.",T1,ST),
            Spacer(1,3),ftable(data['tier1'],T1,BG1,ST),Spacer(1,10)]))
    if data.get('tier2'):
        story.append(KeepTogether([hdr("TIER 2: FUNCTIONAL AND MECHANICAL","Primary negotiation targets.",T2,ST),
            Spacer(1,3),ftable(data['tier2'],T2,BG2,ST,cr=True),Spacer(1,10)]))
    if data.get('tier3'):
        story.append(KeepTogether([hdr("TIER 3: COSMETIC AND MAINTENANCE","Normal wear items.",T3,ST),
            Spacer(1,3),ftable(data['tier3'],T3,BG3,ST),Spacer(1,10)]))

    # CODE ADVISORY
    if data.get('code_advisory'):
        story.append(KeepTogether([hdr("CODE ADVISORY","Grandfathered conditions. No seller obligation to correct.",CODE,ST),Spacer(1,7)]))
        for ci in data['code_advisory']:
            story.append(Paragraph(ci.get('item',''), ST['code_l']))
            story.append(Paragraph(f"<b>Code context:</b> {ci.get('code','')}", ST['ib'])); story.append(Spacer(1,3))
            story.append(Paragraph(f"<b>Risk profile:</b> {ci.get('risk','')}", ST['ib'])); story.append(Spacer(1,3))
            story.append(Paragraph(f"<b>Est. cost to correct:</b> {ci.get('cost','')}", ST['ib'])); story.append(Spacer(1,3))
            story.append(Paragraph(f"<b>Seller obligation:</b> {ci.get('obligation','')}", ST['ib'])); story.append(Spacer(1,6))
        story.append(Paragraph("Code advisory items do not affect insurability and are disclosed solely for buyer awareness.", ST['disc']))
        story.append(Spacer(1,10))

    # NEGOTIATION RECOMMENDATION
    neg = data.get('negotiation', {})
    story.append(KeepTogether([hdr("NEGOTIATION RECOMMENDATION",
        "Practical guidance on structuring requests. Complete the intake questionnaire for deal-specific advice.",NEG,ST),Spacer(1,7)]))

    if neg.get('addendum'):
        story.append(Paragraph("Items to Put in a Repair Addendum", ST['neg_h']))
        story.append(Paragraph("Better resolved by the seller before closing — source unknown, needs verification, or simple enough that seller completion is cleanest.", ST['neg_b']))
        story.append(Spacer(1,5))
        add_rows=[[Paragraph("Item",ST['ch']),Paragraph("Why a Repair, Not a Credit",ST['ch'])]]
        for r in neg['addendum']:
            add_rows.append([Paragraph(r.get('item',''),ST['cb']),Paragraph(r.get('why',''),ST['cv'])])
        at=Table(add_rows,colWidths=[2.2*inch,4.95*inch])
        ac=[('BACKGROUND',(0,0),(-1,0),NEG),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
            ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('GRID',(0,0),(-1,-1),0.35,RULE)]
        for i in range(1,len(add_rows)): ac.append(('BACKGROUND',(0,i),(-1,i),BGNEG if i%2==1 else WHITE))
        at.setStyle(TableStyle(ac)); story.append(at); story.append(Spacer(1,10))

    if neg.get('credit'):
        story.append(Paragraph("Items to Bundle into a Credit Request", ST['neg_h']))
        story.append(Paragraph("Better as a lump credit — seller access impractical, buyer benefits from controlling contractor selection, or items cleaner bundled.", ST['neg_b']))
        story.append(Spacer(1,5))
        cr_rows=[[Paragraph("Item",ST['ch']),Paragraph("Est. Range",ST['ch']),Paragraph("Rationale / Notes",ST['ch'])]]
        for r in neg['credit']:
            cr_rows.append([Paragraph(r.get('item',''),ST['cb']),Paragraph(r.get('rng',''),ST['cv']),Paragraph(r.get('why',''),ST['cv'])])
        tl = neg.get('total_low',0); th = neg.get('total_high',0)
        cr_rows.append([Paragraph("TOTAL CREDIT REQUEST RANGE",ST['cb']),
                        Paragraph(f"${tl:,} - ${th:,}",ST['cb']),Paragraph("",ST['cv'])])
        ct=Table(cr_rows,colWidths=[2.1*inch,0.90*inch,4.15*inch])
        cc=[('BACKGROUND',(0,0),(-1,0),NEG),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
            ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('GRID',(0,0),(-1,-1),0.35,RULE),
            ('BACKGROUND',(0,len(cr_rows)-1),(-1,len(cr_rows)-1),colors.HexColor("#D5E8D4")),
            ('LINEABOVE',(0,len(cr_rows)-1),(-1,len(cr_rows)-1),1.0,NEG)]
        for i in range(1,len(cr_rows)-1): cc.append(('BACKGROUND',(0,i),(-1,i),BGNEG if i%2==1 else WHITE))
        ct.setStyle(TableStyle(cc)); story.append(ct); story.append(Spacer(1,10))

    if neg.get('info_only'):
        story.append(Paragraph("Items That Are Informational Only", ST['neg_h']))
        story.append(Paragraph("Not recommended as negotiation points — low cost, needs evaluation first, or not worth the goodwill.", ST['neg_b']))
        story.append(Spacer(1,5))
        info_rows=[[Paragraph("Item",ST['ch']),Paragraph("Rationale",ST['ch'])]]
        for r in neg['info_only']:
            info_rows.append([Paragraph(r.get('item',''),ST['cb']),Paragraph(r.get('why',''),ST['cv'])])
        it=Table(info_rows,colWidths=[2.5*inch,4.65*inch])
        ic=[('BACKGROUND',(0,0),(-1,0),MG),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
            ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('GRID',(0,0),(-1,-1),0.35,RULE)]
        for i in range(1,len(info_rows)): ic.append(('BACKGROUND',(0,i),(-1,i),LG if i%2==1 else WHITE))
        it.setStyle(TableStyle(ic)); story.append(it)
    story.append(Spacer(1,6))
    story.append(Paragraph("This recommendation is general and does not account for deal-specific variables. Complete the intake questionnaire for tailored advice.",ST['disc']))
    story.append(Spacer(1,10))

    # TALKING POINTS
    if data.get('talking_points'):
        story.append(KeepTogether([hdr("TALKING POINTS FOR YOUR BUYER","Use these to walk your client through findings in plain language.",LB,ST),Spacer(1,7)]))
        for tp in data['talking_points']:
            story.append(Paragraph(tp.get('label',''), ST['ti']))
            story.append(Paragraph(tp.get('text',''), ST['tb']))
            story.append(Spacer(1,6))
        story.append(Spacer(1,4))

    # TAILORED INPUTS
    prop_addr = data.get('property', {}).get('address', '')
    insp_date = data.get('property', {}).get('inspection_date', '')
    import urllib.parse
    neg_url = f"/negotiate?property={urllib.parse.quote(prop_addr)}&date={urllib.parse.quote(insp_date)}"

    story.append(KeepTogether([hdr("TAILORED NEGOTIATION INPUTS",
        "Get a deal-specific strategy by answering a few questions about your transaction.",NAVY,ST),
        Spacer(1,8),
        Paragraph(
            "The negotiation recommendation above is based on the inspection findings alone. "
            "For a strategy tailored to your specific deal — seller situation, days on market, "
            "offer dynamics, and your read on seller flexibility — complete the short questionnaire below.",
            ST['nq']),
        Spacer(1,6),
        Paragraph(
            f"<b>Get your tailored strategy:</b> Visit <b>hope-agent-brief.onrender.com/negotiate"
            f"?property={urllib.parse.quote(prop_addr)}</b> on any device. "
            "Answer 10 questions and download your Negotiation Addendum PDF in about 30 seconds.",
            ST['nq']),
        Spacer(1,6),
        Paragraph(
            "Questions? Reach Nick directly at <b>(813) 777-6265</b> call or text, "
            "or email Nick-L@hopehomeinspections.com.",
            ST['nq']),
        Spacer(1,10)]))

    # DISCLAIMER
    story.append(HRFlowable(width=CW,thickness=0.4,color=RULE)); story.append(Spacer(1,5))
    story.append(Paragraph(
        "This brief is prepared as a professional courtesy to assist real estate agents in communicating inspection findings to their clients. "
        "It does not replace the full inspection report, which remains the definitive document of record. Repair cost estimates are ranges based on "
        "current Tampa Bay area market rates and are not guarantees of contractor pricing. Insurance assessments are based solely on the completed "
        "4-point inspection. Wind mitigation summaries are based on the completed wind mitigation inspection form. "
        "This document is prepared solely for the agent named above.",ST['disc']))

    fn = on_page(logo_path)
    doc.build(story, onFirstPage=fn, onLaterPages=fn)

# ── Routes ─────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    try:
        year_built = request.form.get('year_built', '').strip()
        if not year_built:
            return jsonify({'error': 'Year built is required.'}), 400

        inspection_file = request.files.get('inspection_pdf')
        if not inspection_file:
            return jsonify({'error': 'Full home inspection PDF is required.'}), 400

        inspection_text = extract_pdf_text(inspection_file.read())

        fourpoint_text = None
        if 'fourpoint_pdf' in request.files and request.files['fourpoint_pdf'].filename:
            fourpoint_text = extract_pdf_text(request.files['fourpoint_pdf'].read())

        windmit_text = None
        if 'windmit_pdf' in request.files and request.files['windmit_pdf'].filename:
            windmit_text = extract_pdf_text(request.files['windmit_pdf'].read())

        wdo_text = None
        if 'wdo_pdf' in request.files and request.files['wdo_pdf'].filename:
            wdo_text = extract_pdf_text(request.files['wdo_pdf'].read())

        # Analyze with Claude
        data = analyze_with_claude(
            inspection_text, year_built,
            fourpoint_text, windmit_text, wdo_text
        )

        # Build PDF
        logo_path = get_logo_path()
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            output_path = f.name

        build_pdf(data, logo_path, output_path)

        address = data.get('property', {}).get('address', 'Agent_Advisory')
        safe_addr = "".join(c for c in address if c.isalnum() or c in ' _-').strip().replace(' ', '_')
        filename = f"Agent_Advisory_{safe_addr}.pdf"

        return send_file(output_path, as_attachment=True,
                        download_name=filename, mimetype='application/pdf')

    except json.JSONDecodeError as e:
        return jsonify({'error': f'Failed to parse Claude response as JSON: {str(e)}'}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

# ── Negotiation routes ─────────────────────────────────────────────
from negotiate import analyze_negotiation, build_addendum as build_neg_addendum

@app.route('/negotiate')
def negotiate_form():
    return render_template('negotiate.html')

@app.route('/negotiate/generate', methods=['POST'])
def negotiate_generate():
    try:
        form_data = {k: request.form.get(k, '') for k in request.form}

        strategy = analyze_negotiation(form_data, ANTHROPIC_API_KEY)

        logo_path = get_logo_path()
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            output_path = f.name

        build_neg_addendum(form_data, strategy, logo_path, output_path)

        addr = form_data.get('property_address', 'Property')
        safe = "".join(c for c in addr if c.isalnum() or c in ' _-').strip().replace(' ', '_')
        filename = f"Negotiation_Addendum_{safe}.pdf"

        return send_file(output_path, as_attachment=True,
                        download_name=filename, mimetype='application/pdf')

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
