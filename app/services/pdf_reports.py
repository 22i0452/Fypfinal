"""On-demand summaries of stored versions/results. No model calls or new facts."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, KeepTogether

ROOT = Path(__file__).resolve().parents[2]


def render_pdf(title, subtitle, sections, *, status, reference):
    font = ROOT / 'scribe/assets/fonts/DejaVuSans.ttf'
    if 'MedflowSans' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('MedflowSans', str(font)))
    styles = getSampleStyleSheet()
    body = ParagraphStyle('MFBody', fontName='MedflowSans', fontSize=10, leading=17,
                          textColor=colors.HexColor('#303b38'), spaceAfter=10, splitLongWords=True)
    heading = ParagraphStyle('MFHeading', parent=body, fontSize=11, leading=16,
                             textColor=colors.HexColor('#15584a'), spaceBefore=14, spaceAfter=8)
    urdu = ParagraphStyle('MFUrdu', parent=body, alignment=TA_RIGHT, leading=20)

    def paragraph(text, style=body):
        text = str(text or 'Not documented.')
        if re.search('[\u0600-\u06ff]', text):
            import arabic_reshaper
            from bidi.algorithm import get_display
            text = get_display(arabic_reshaper.reshape(text))
            style = urdu
        return Paragraph(escape(text).replace('\n','<br/>'), style)

    stream = BytesIO()
    document = SimpleDocTemplate(stream, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm,
        topMargin=19*mm, bottomMargin=22*mm, title=title, author='Medflow Clinical Studio')
    title_style = ParagraphStyle('MFTitle', parent=styles['Title'], fontName='MedflowSans',
                                fontSize=28, leading=32, alignment=0, spaceAfter=12)
    content = [paragraph('MEDFLOW  /  CLINICAL STUDIO', heading), paragraph(title, title_style),
               paragraph(subtitle), paragraph(status, heading),
               HRFlowable(width='100%', color=colors.HexColor('#d5dfdb')), Spacer(1, 8)]
    for label, lines in sections:
        content.append(KeepTogether([paragraph(label,heading), paragraph(lines[0] if lines else 'Not documented.')]))
        content.extend(paragraph(line) for line in lines[1:])

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#d5dfdb'))
        canvas.line(20*mm,17*mm,A4[0]-20*mm,17*mm)
        canvas.setFont('MedflowSans',7)
        canvas.setFillColor(colors.HexColor('#52655e'))
        canvas.drawString(20*mm,12*mm,reference[:100])
        canvas.drawRightString(A4[0]-20*mm,12*mm,f'Page {doc.page}')
        canvas.restoreState()

    document.build(content,onFirstPage=footer,onLaterPages=footer)
    return stream.getvalue()


def visit_pdf(payload, patient, doctor, *, technical=False):
    approved = payload['state'] == 'APPROVED_BY_DOCTOR'
    soap = payload['soap']
    sections = [('Patient & visit', [f"{patient.name} | Age: {patient.age_text or 'Not documented'}",
                    f"Doctor: {doctor} | Encounter: {payload['encounter_id']}"])]
    sections.extend((label,[soap.get(key,'')]) for key,label in [
        ('subjective','History'),('objective','Documented findings'),
        ('assessment','Assessment'),('plan','Plan & follow-up')])
    cards = soap.get('medicine_evidence',{}).get('items',[])
    if approved and not technical:
        instructions = list(dict.fromkeys(link['text'] for card in cards
                          for link in card['soap_links'] if link['section']=='plan'))
        if instructions:
            sections.append(('Medication instructions - as documented', instructions + [
                'Only the instructions stated in the approved Plan are reproduced. '
                'No dose, frequency, duration or replacement medicine has been added.']))
    if technical:
        sections.append(('Evidence scope',[soap.get('medicine_evidence',{}).get('scope','')]))
        for card in cards:
            catalogue = card.get('catalogue') or {}
            sections.append((f"Medicine: {card['final_name']} | Source {card['utterance_id']}",[
                card['original'], f"English: {card['translation']}",
                f"Proposed: {card['proposed_name']} | Confirmed: {card.get('confirmed_name') or 'No explicit spelling confirmation'}",
                f"Catalogue: {catalogue.get('name','No exact match')} | Reference: {catalogue.get('source_filename') or catalogue.get('source_url') or 'None'}",
                f"Doctor wording review: {'Recorded' if card['doctor_reviewed'] else 'Not recorded'} | SOAP sections: {', '.join(link['section'] for link in card['soap_links']) or 'Missing'}",
            ]))
        sections.append(('Recorded limitations', soap.get('structured_soap',{}).get('warnings',[]) or ['Source linkage does not establish clinical correctness.']))
    return render_pdf('Technical Evidence Report' if technical else 'Visit Summary',
        f"Visit {payload['created_at'][:10]} | Note version {payload['version']}", sections,
        status=('Doctor approved' if approved else 'DRAFT - not approved for patient use') + ' | FYP synthetic-data demonstration',
        reference=f"{payload['note_id']} / v{payload['version']} - Synthetic demo; not a clinical prescription")


def prescription_pdf(payload, patient, doctor):
    """Readable Rx sheet with separately labelled stops and doctor-entered fields."""
    from reportlab.platypus import LongTable, TableStyle
    prescription = payload['soap']['prescription']
    stream = BytesIO()
    if 'MedflowSans' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('MedflowSans', str(Path(__file__).resolve().parents[2] / 'scribe/assets/fonts/DejaVuSans.ttf')))
    styles = getSampleStyleSheet()
    body = ParagraphStyle('RxBody', fontName='MedflowSans', fontSize=9.5, leading=14,
        textColor=colors.HexColor('#283b35'), spaceAfter=7, splitLongWords=True)
    heading = ParagraphStyle('RxHeading', parent=body, fontSize=10, leading=15,
        textColor=colors.HexColor('#15584a'), spaceBefore=13, spaceAfter=7)
    title = ParagraphStyle('RxTitle', parent=body, fontSize=30, leading=36, spaceAfter=8)
    small = ParagraphStyle('RxSmall', parent=body, fontSize=7.5, leading=11)

    def p(value, style=body):
        text = str(value or 'Not documented')
        if re.search('[\u0600-\u06ff]', text):
            import arabic_reshaper
            from bidi.algorithm import get_display
            text = get_display(arabic_reshaper.reshape(text))
        return Paragraph(escape(text).replace('\n', '<br/>'), style)

    content = [p('MEDFLOW / CLINICAL STUDIO', heading), p('Prescription', title),
        p(f"{doctor} | {payload['created_at'][:10]} | Doctor-approved version {payload['version']}", small),
        HRFlowable(width='100%', color=colors.HexColor('#c7d3cd')), Spacer(1, 10),
        p(f"{patient.name} | Age: {patient.age_text or 'Not documented'}"),
        p(f"Encounter {payload['encounter_id']}", small)]
    soap = payload['soap']
    for label, value in [('Symptoms & history', soap['subjective']), ('Findings', soap['objective']), ('Assessment', soap['assessment'])]:
        content.extend([p(label, heading), p(value)])
    content.append(p('Rx / Medication instructions', heading))
    positive = [r for r in prescription['medicines'] if r['action'] in {'take', 'continue'}]
    caution = [r for r in prescription['medicines'] if r['action'] in {'stop', 'avoid'}]
    if positive:
        rows = [[p('MEDICINE', small), p('DOSE / ROUTE', small), p('WHEN / HOW LONG', small)]]
        for r in positive:
            rows.append([p(r['name'] + '\n' + r['action'].title()),
                p((r['dose'] or 'Dose not documented') + '\n' + (r['route'] or 'Route not documented')),
                p((r['frequency'] or 'Frequency not documented') + '\n' + (r['duration'] or 'Duration not documented'))])
            rows.append([p('Instructions: ' + r['instructions']), '', ''])
        table = LongTable(rows, colWidths=[61*mm, 49*mm, 60*mm], repeatRows=1, splitInRow=1, hAlign='LEFT')
        commands = [('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#edf3ef')), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 9), ('RIGHTPADDING', (0, 0), (-1, -1), 9),
            ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LINEBELOW', (0, 0), (-1, 0), .6, colors.HexColor('#c7d3cd'))]
        for i in range(2, len(rows), 2):
            commands.extend([('SPAN', (0, i), (-1, i)), ('LINEBELOW', (0, i), (-1, i), .4, colors.HexColor('#dce5df'))])
        table.setStyle(TableStyle(commands)); content.append(table)
    else:
        content.append(p('No take/continue medication instructions recorded.'))
    if caution:
        content.append(p('Stop / Avoid', heading))
        for r in caution:
            content.extend([p(r['action'].upper() + ' ' + r['name'], heading), p(r['instructions'])])
    for key, label in [('tests', 'Tests & investigations'), ('advice', 'Advice'), ('follow_up', 'Follow-up')]:
        content.extend([p(label, heading), p(prescription.get(key))])
    content.extend([Spacer(1, 10), HRFlowable(width='100%', color=colors.HexColor('#c7d3cd')),
        p('Recorded and approved by ' + doctor, heading),
        p('Doctor-entered prescription fields are recorded separately from the original conversation. Blank fields have not been guessed. FYP synthetic-data demonstration.', small)])
    doc = SimpleDocTemplate(stream, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=16*mm,
        bottomMargin=21*mm, title='Medflow Prescription', author=doctor)

    def footer(canvas, document):
        canvas.saveState(); canvas.setFont('MedflowSans', 7); canvas.setFillColor(colors.HexColor('#52655e'))
        canvas.drawString(20*mm, 11*mm, f"{payload['note_id']} / v{payload['version']} | FYP demonstration")
        canvas.drawRightString(A4[0]-20*mm, 11*mm, f'Page {document.page}'); canvas.restoreState()
    doc.build(content, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()


def _rate_text(rate):
    return f"{rate['numerator']} / {rate['denominator']} ({rate['percent']}%)" if rate.get('denominator') else 'Not tested'


def testing_pdf(report):
    from app.testing.evaluation import scores
    measured=scores(report);timing=measured['timings']
    sections=[('Measured summary',[
        'Scenario success: '+_rate_text(measured['success'])+' | Completed assertions: '+_rate_text(measured['checks']),
        'Attempted / planned: '+_rate_text(measured['completion'])+' | '+' | '.join(f'{key}: {value}' for key,value in report['totals'].items()),
        f"Median: {timing['median_ms']} ms | p95: {timing['p95_ms']} ms | n={timing['n']} completed case timings. Includes setup and checks.",
        f"Run wall time: {report.get('duration_ms')} ms. {report['timing_scope']}"]),
        ('Coverage by category',[
            f"{row['name']}: {_rate_text(row)} | {row['failed']} failed | {row['errors']} errors | {row['unassessed']} not evaluated"
            for row in measured['categories']]),
        ('Checks by purpose',[
            f"{key.replace('_',' ')}: {_rate_text(rate)}" for key,rate in measured['metrics'].items()
            if rate['denominator']] or ['No purpose-tagged assertions in this saved pack.'])]
    if measured['audio']['clips']:
        audio=measured['audio']
        sections.append(('Recorded audio measurements',[
            f"ASR-scored recordings: {audio['clips']} | Raw ASR word error rate: {_rate_text(audio['word_error_rate'])}",
            'Raw ASR character error rate: '+_rate_text(audio['character_error_rate']),
            'Medicine name precision: '+_rate_text(audio['medicine_precision'])+' | Recall: '+_rate_text(audio['medicine_recall']),
            'Contextual text role agreement: '+_rate_text(audio['roles']),
            'WER/CER use NFKC, casefold and punctuation/diacritic removal; no spelling correction. WER may exceed 100%. Role agreement uses distinct greedy text alignment, not acoustic DER. References are uploader-attested fictional scripts, not independent annotations.']))
    failures=[case for case in report['cases'] if case['status'] in {'FAILED','ERROR'}]
    sections.append(('Failures and errors', [f"{len(failures)} cases need attention. Full per-case artifacts and assertions remain in the Cases tab and JSON export."]))
    for case in failures:
        lines=[f"Input: {case['input']}",f"Expected: {case['expected']}",f"Scope: {case['scope']}"]
        for check in case.get('checks',[]):
            if check['status']=='FAILED':
                lines.append(f"FAILED - {check['label']} | Expected: {str(check['expected'])[:1000]} | Actual: {str(check['actual'])[:1000]}")
        if case.get('error'):lines.append(case['error']['message'])
        if not case.get('checks'):lines.append('No completed assertions; not counted as a pass.')
        sections.append((case['title']+' - '+case['status'],lines))
    sections.extend([
        ('Reproducibility receipt',[
            f"Run: {report['run_id']} | Pack: {report['pack_version']} | Mode: {report['mode']} | Repetitions: {report.get('repetitions',1)}",
            f"Protocol: {report.get('evaluation_protocol','Legacy pack; not comparable')}",
            f"Reference SHA256: {report.get('reference_sha256','Not recorded')}",
            f"Application source SHA256: {report.get('environment',{}).get('source_sha256','Not recorded')}",
            f"Provider: {report.get('environment',{}).get('provider','Not recorded')} | Model: {report.get('environment',{}).get('model') or 'Controlled fixture'}"]),
        ('Evaluation limits',[
            'Small authored pack. Synthetic results check software behavior with controlled providers and isolated storage. Live text tests factual wording without audio. Recorded audio tests files through the pipeline, not browser microphone or telephone capture.',
            'Source links and doctor wording confirmation do not establish clinical correctness. Percentages are sample measurements, not model confidence. Stopped, interrupted and unexecuted cases are never passes. No baseline or improvement is invented.',
            'Untested: '+ '; '.join(report.get('unassessed',[]))])])
    return render_pdf('Evaluation Report',report['started_at'],sections,status=report['status'],reference=report['run_id'])


def comparison_pdf(baseline,current):
    from app.testing.evaluation import comparison
    result=comparison(baseline,current)
    delta=result['success_delta_pp']
    sections=[('Comparison eligibility',[
        f"Observed scenario success change: {delta:+.2f} percentage points." if delta is not None else 'No improvement percentage available. '+ '; '.join(result['reasons']),
        result['scope']]),
        ('Measured outcomes',[
            f"Baseline: {_rate_text(result['baseline']['success'])} | Current: {_rate_text(result['current']['success'])}",
            f"Median case wall time: {result['baseline']['timings']['median_ms']} ms -> {result['current']['timings']['median_ms']} ms. Includes setup and checks.",
            *[f"{row['name']}: {_rate_text(row['baseline']) if row['baseline'] else 'Not tested'} -> {_rate_text(row['current'])}"+
                 (f" | {row['delta_pp']:+.2f} pp" if row['delta_pp'] is not None else ' | Not comparable') for row in result['categories']]]),
        ('Run receipts',[
            f"Baseline: {baseline['run_id']} | {baseline['started_at']} | {baseline['status']}",
            f"Current: {current['run_id']} | {current['started_at']} | {current['status']}",
            f"Pack: {current['pack_version']} | Protocol: {current.get('evaluation_protocol','Not recorded')}",
            f"Baseline application SHA256: {baseline.get('environment',{}).get('source_sha256','Not recorded')}",
            f"Current application SHA256: {current.get('environment',{}).get('source_sha256','Not recorded')}",
            'Small fixed samples; no statistical significance or clinical accuracy claim. Different code with matching references is an observed before/after comparison, not proof of causality.'])]
    return render_pdf('Evaluation Comparison',current['started_at'],sections,
        status='Comparable fixed runs' if result['compatible'] else 'Not comparable',reference=current['run_id'])
