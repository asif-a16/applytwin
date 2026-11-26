"""Application-question answer bank.

Every application asks the same ~40 questions in different words. The bank stores one truthful answer per
question type; match() maps any wording to the right answer with a confidence. Below the threshold the agent
must ask the user (and save the answer so it never asks twice).
"""
import re
import time

from . import blockers
from . import regions
from .store import nodash

STOP = set('a an the of to for in on and or is are you your do does did be been have has with at by as this that '
           'will would can could please any if from our we us it its which what when where who how'.split())


def _yn(b):
    """True/False -> Yes/No; None (never answered) -> '' so the twin asks instead of guessing."""
    return '' if b is None else ('Yes' if b else 'No')


US_YEARS = ['Freshman', 'Sophomore', 'Junior', 'Senior']
YEARS = US_YEARS
UK_YEARS = ['First year', 'Second year', 'Third year', 'Fourth year', 'Final year']


def standing(p):
    # (now, during a summer internship): a sophomore today is a rising junior next summer; a UK second year is going into
    # third year (or their final year, which the user says by picking "Final year" once they are in it)
    raw = (p.get('class_standing') or '').strip()
    now = raw.title() if raw.title() in US_YEARS else raw
    if now in US_YEARS:
        i = US_YEARS.index(now)
        return now, ('Rising ' + US_YEARS[i + 1]) if i < 3 else 'Senior'
    low = now.lower()
    uk = [y.lower() for y in UK_YEARS]
    if low in uk[:3]:
        return now, 'Going into ' + UK_YEARS[uk.index(low) + 1].lower()
    if low == 'placement year':
        return now, 'Going into final year'
    if low in ('fourth year', 'final year'):
        return now, now
    return now, ''


def _region_part(loc):
    '''"Austin, TX" -> "TX", "Leeds, West Yorkshire" -> "West Yorkshire"; "Leeds, UK" -> '' (a country is not a county).'''
    parts = [x.strip() for x in loc.split(',')]
    if len(parts) < 2 or not parts[1] or (regions.country_code(parts[1]) and parts[1].upper() not in regions.STATES):
        return ''
    return parts[1]


def class_kind(p):
    '''"Predicted" until the graduation month has passed, then "Achieved"; '' when the date is too vague to tell.'''
    if not p.get('degree_class'):
        return ''
    gy = re.search(r'20\d\d', str(p.get('grad_year') or ''))
    if not gy:
        return ''
    y, now = int(gy.group()), time.gmtime()
    mi = next((i + 1 for i, m in enumerate(MONTHS) if m[:3].lower() == str(p.get('grad_month') or '').strip()[:3].lower()), 0)
    if y != now.tm_year:
        return 'Predicted' if y > now.tm_year else 'Achieved'
    if not mi:
        return ''
    return 'Achieved' if mi < now.tm_mon else 'Predicted'


def gpa_value(p):
    '''The GPA to give a form: never a UK degree class ("2:1" is not a grade point average); the agent asks instead.'''
    g = str(p.get('gpa') or '')
    return '' if regions.UK_CLASS.search(g) and not re.search(r'\d\.\d', g) else g


def default_bank(p):
    s = p.get('eeo', {})
    grad = f"{p.get('grad_month', '')} {p.get('grad_year', '')}".strip()
    school_start = f"{p.get('start_month', '')} {p.get('start_year', '')}".strip()
    email = p.get('school_email') or (p.get('email', '') if re.search(r'\.(edu|ac\.[a-z]{2})\s*$', p.get('email') or '', re.I) else '')
    cls_kind = class_kind(p)
    rows = [
        # UK graduate forms: checked before the US school rows so 'school' / 'grades' / 'degree' never answer them
        ('school_type', 'What type of school did you attend?', r'type of (secondary )?school|school type|(state|independent|private|fee[- ]paying|'
         r'grammar|selective) school[^?]{0,40}(attend|go to|went)|(attend|go to|went to)[^?]{0,40}(state|independent|private|fee[- ]paying|'
         r'grammar|selective) school', s.get('school_type', '')),
        ('free_school_meals', 'Were you eligible for free school meals?', r'free school meals|\bfsm\b', s.get('free_school_meals', '')),
        ('first_generation', 'Are you the first in your family to go to university?',
         r'first[- ](generation|in (your|my|the) (immediate )?family)', s.get('first_generation', '')),
        ('ucas', 'UCAS tariff points', r'\bucas\b', p.get('ucas_points', '')),
        ('a_levels', 'A-level grades (or equivalent)', r'\ba-levels?\b|\balevels?\b|\ba levels? (grades|results|subjects)|\bib (diploma|points|score)|international baccalaureate|'
         r'\bhighers\b|\bbtec\b|level 3 (qualifications|grades|results)', p.get('a_levels', '')),
        ('gcse', 'GCSE results', r'\bgcses?\b|\bigcses?\b|level 2 (qualifications|grades|results)', p.get('gcse', '')),
        ('degree_class_kind', 'Is your degree classification predicted or achieved?',
         r'predicted or (achieved|actual|awarded)|(achieved|actual|awarded) or predicted', cls_kind),
        ('degree_class', 'Predicted or achieved degree classification',
         r'(degree|honours|expected|predicted|achieved|final) (degree )?class(ification)?\b|class(ification)? of (your )?(degree|honours)|'
         r'(degree|honours) (grade|result)|predicted (degree|grade for your degree)', p.get('degree_class', '')),
        ('sexual_orientation', 'Sexual orientation', r'sexual orientation|sexuality', s.get('sexual_orientation', '')),
        ('religion', 'Religion or belief', r'^\s*(religion|faith|belief)\b|religion (or|and|/) belief|religious (belief|affiliation|identity)|'
         r'what is your religion', s.get('religion', '')),
        # asked by quant/trading and campus forms; checked first so 'graduation year' / 'school' never answer them
        ('hs_grad_year', 'High school graduation year', r'high ?school[^?]{0,40}(grad|year|class)|(grad|year|class)[^?]{0,30}high ?school',
         p.get('hs_grad_year', '')),
        ('hs_name', 'High school name', r'high ?school( name)?\b(?![^?]{0,40}(grad|year|class|gpa))|secondary school|sixth[- ]form',
         p.get('high_school', '')),
        ('sat', 'SAT score', r'\bsat\b[^?]{0,30}\bscores?\b|\bscores?\b[^?]{0,20}\bsat\b', p.get('sat_score', '')),
        ('act', 'ACT score', r'\bact\b[^?]{0,15}\bscores?\b|\bscores?\b[^?]{0,20}\bact\b', p.get('act_score', '')),
        ('school_email', 'University email', r'(school|university|college|student|academic|\.edu|\.ac\.uk)[^?]{0,10}e-?mail', email),
        ('school_start', 'When did you start at your university?',
         r'(start|began|begin|enrollment|matriculation|attendance)\s*(date|month|year|term)\b[^?]{0,30}\b(university|college|school|'
         r'program|degree|studies)|(university|college|school|degree|studies)[^?]{0,20}\b(start|begin|enrollment|matriculation|attendance)'
         r'\s*(date|month|year|term)|attendance start|attended from|when did you (start|begin|enroll|matriculate)|'
         r'(what|which) (month|year|term|semester) did you (start|begin|enroll|matriculate)|(date|month|year) (you )?(started|began|enrolled|matriculated)',
         school_start),
        ('availability', 'What are your internship dates / availability?',
         r'(internship|placement) (dates|availability|term)|dates? (of|for) (your )?(internship )?availability|availab\w+ (dates|window|period)|'
         r'what dates (are|would|will) you (be )?available', p.get('availability', '')),
        ('applied_before', 'Have you applied to this company before?',
         r'\b(have|did|has) you (ever |previously |already |recently )?(applied|submitted an application|interviewed)\b|'
         r'prior applications? (to|with|at|for)|previously applied|applied (to|with|at) [^?]{0,40}\b(before|previously|in the past)', ''),
        ('knows_employee', 'Do you know anyone / have relatives who work here?',
         r'^(?!.*\bhear\b)(?=.*\b(know|related to|relatives?|family members?|friends?|relationships?)\b).*(know|related to|relatives?|family members?|friends?|relationships?)\b[^?]{0,50}\b(employ|works? (at|for)|working (at|for)|'
         r'currently work|director|officer)', _yn(p.get('knows_employee'))),
        ('political', 'Have you made political contributions?', r'political (contribution|donation)|campaign contribution|'
         r'contribut\w+ to [^?]{0,40}(candidate|campaign|political)', _yn(p.get('political_contributions'))),
        ('offers', 'Do you have other offers or deadlines?',
         r'(current|other|existing|competing|outstanding|pending|active) (job |internship |return )?offers?|offer deadlines?|'
         r'recruiting (timelines?|deadlines?)|deadlines?[^?]{0,30}(offer|decision|recruit)', p.get('offers', '')),
        ('work_auth', 'Are you legally authorized to work in the United States?',   # UK and other countries: regions.answer_rows
         r'(legally )?(authori[sz]ed|eligible|permitted) to work|work authori[sz]ation|right to work', _yn(p.get('work_authorized_us'))),
        ('sponsorship', 'Will you now or in the future require visa sponsorship?',
         r'sponsor|h-?1b|visa status|immigration (support|assistance)', _yn(p.get('needs_sponsorship'))),
        ('citizenship', 'What is your citizenship status?', r'citizen(ship)?\b(?! of)|u\.?s\.? person|green card|permanent resident',
         p.get('citizenship') or ''),
        ('relocate', 'Are you willing to relocate?', r'relocat', _yn(p.get('willing_to_relocate'))),
        ('onsite', 'Are you able to work on-site / hybrid at this location?', r'on-?site|in[- ]office|in person|hybrid|commut',
         _yn(p.get('onsite_ok'))),
        ('start', 'When can you start?', r'start date|available to start|earliest (start|date)|when can you (start|begin)',
         p.get('earliest_start', '')),
        ('grad_year', 'Graduation year', r'graduation year|class of|year of graduation|(what|which) year (will|do) you graduate', p.get('grad_year', '')),
        ('grad', 'What is your expected graduation date?', r'graduat(ion|e) (date|month)|expected graduation|when (do|will) you graduate',
         grad),
        ('standing', 'What is your current class standing / year in school?',
         r'class (standing|level|year)|(current|academic) (year|standing)|year (in|at) (school|college|university)|what year are you|'
         r'year of (study|studies|your (degree|course))|stage of (your )?(degree|course|studies)',
         standing(p)[0]),
        ('standing_summer', 'What will your class standing be during the internship?',
         r'rising|standing (during|at the time)|year (during|at the time of) the internship|(entering|going into) your',
         standing(p)[1]),
        ('school', 'School / university', r'(school|university|college|institution)( name)?$|which (school|university)|'
         r'(university|institution) (you|are you) (attend|study|studying)|where (do|did) you study',
         p.get('school', '')),
        ('degree', 'Degree', r'^degree(?! (subject|title|name|course|discipline|classification|class))|degree (type|level|pursuing)|'
         r'highest (level of )?education|degree are you', p.get('degree', '')),
        ('major', 'Major / field of study', r'major|field of study|discipline|area of study|concentration|(degree|course) (subject|title|name)|'
         r'subject (of|you are) (study|studying)|what (are you|did you) study', p.get('major', '')),
        ('gpa', 'GPA', r'\bgpa\b|grade point', gpa_value(p)),
        ('enrolled', 'Are you currently enrolled in a degree program?', r'currently (enrolled|pursuing|a student)|enrolled in',
         _yn(p.get('enrolled'))),
        ('age', 'Are you at least 18 years old?', r'18 (years|or older)|at least 18|over the age', _yn(p.get('over_18'))),
        ('background', 'Will you consent to a background check?', r'background (check|screen)|drug (test|screen)|\bdbs\b|\bbpss\b|'
         r'(security|pre-employment) (vetting|screening|clearance check)|vetting (check|process)', _yn(p.get('background_check_ok'))),
        ('hear', 'How did you hear about us?', r'how did you (hear|find|learn)|source of (application|referral)|where did you (hear|find)',
         'Company careers website'),
        ('government', 'Are you a current or former government employee?',
         r'government (official|employee|entity|agency)|employee of (the |a |any )?(u\.?s\.? |federal |state |uk |hm )?government|public official|'
         r'federal employee|civil serv(ant|ice)',
         _yn(p.get('government_employee'))),
        ('prior_employee', 'Have you previously worked for this company?',
         r'^(?!.*government)(?=.*(previously|ever|currently|before|former))(.*(employed|worked) (by|for|at)|.*former employee)', 'No'),
        ('referral', 'Were you referred by an employee?', r'\breferr(ed|al)\b|who referred', 'No'),
        ('noncompete', 'Are you subject to a non-compete or non-solicit agreement?', r'non-?compete|non-?solicit|restrictive covenant',
         _yn(p.get('has_noncompete'))),

        ('salary', 'What are your salary expectations?', r'salary|compensation (expectation|requirement)|pay (expectation|range)|desired (pay|rate)',
         p.get('salary_expectation', '')),
        ('first_name', 'First name', r'^(legal |preferred )?(first|given) name|^preferred name', (p.get('name') or '').split(' ')[0]),
        ('last_name', 'Last name', r'^(legal )?(last|family) name|^surname', (p.get('name') or '').split(' ')[-1] if ' ' in (p.get('name') or '') else ''),
        ('full_name', 'Full name', r'^(full |legal )?name$|^(your )?full (legal )?name', p.get('name', '')),
        ('linkedin', 'LinkedIn profile', r'linkedin', p.get('linkedin', '')),
        ('github', 'GitHub', r'github', p.get('github', '')),
        ('website', 'Website / portfolio', r'website|portfolio|personal (site|url)', p.get('website', '')),
        ('phone', 'Phone', r'^(phone|mobile|cell)', p.get('phone', '')),
        ('email', 'Email', r'^e-?mail', p.get('email', '')),
        # forms that split the address into fields (checked before the combined 'location' question)
        ('address2', 'Address line 2', r'address line ?2|address ?2\b|apartment|suite|\bunit\b|\bapt\b', p.get('address2', '')),
        ('address', 'Street address', r'^(home |mailing |current |street |permanent |residential )?address( line ?1| ?1)?\b(?!.*e-?mail)|^street', p.get('address', '')),
        ('city', 'City', r'^(current )?city\b(?!,? ?(and|&|/) ?state)|^town\b', (p.get('location', '') or '').split(',')[0].strip()),
        ('state', 'County / state / province', r'^(state|province|region|county)( or province| / province| or state)?( of residence)?$', _region_part(p.get('location') or '')),
        ('postal_code', 'Postcode', r'\bzip\b|postal|post code|postcode', p.get('postal_code', '')),
        ('country', 'Country', r'^(current )?country( of residence)?$|^country\b(?!.*(citizen|authori))', p.get('country', '')),
        ('location', 'Current location', r'(?<![a-z])(current )?(location|city)( of residence)?$|city,? ?(and|&|/) ?state|where are you (located|based)', p.get('location', '')),
        ('gender', 'Gender', r'\bgender\b|\bsex\b', s.get('gender', '')),
        ('race', 'Ethnicity', r'\brace\b|ethnic', s.get('race', '')),
        ('hispanic', 'Are you Hispanic or Latino?', r'hispanic|latin[oax]', s.get('hispanic', '')),
        ('veteran', 'Veteran status', r'veteran|military (service|status)|armed forces|served in the (forces|military)', s.get('veteran', '')),
        ('disability', 'Disability status', r'disab|long[- ]term (health )?condition|equality act', s.get('disability', '')),
        ('pronouns', 'Pronouns', r'pronoun', s.get('pronouns', '')),
        ('sms', 'Do you consent to SMS / text messages?', r'\bsms\b|text messag', _yn(p.get('sms_ok'))),
        # an AI-led or AI-scored interview step (HireVue, Paradox, "AI interviewer"): consenting keeps the application alive
        ('ai_interview', 'Do you consent to an AI-assisted interview?',
         r'\b(ai|artificial intelligence)\b[^?]{0,60}\binterview|\binterview[^?]{0,60}\b(ai|artificial intelligence)\b|hirevue|'
         r'\b(ai|artificial intelligence)[- ](powered|assisted|led|enabled|based)\b[^?]{0,40}(assessment|screen)',
         'No' if p.get('ai_review_ok') is False else 'Yes'),
        ('ai_review', 'May AI tools help review your application?', r'automated tools|\bai\b.*(review|process)', _yn(p.get('ai_review_ok'))),
        ('arbitration', 'Do you agree to the arbitration agreement?', r'arbitrat|class[- ]action waiver|jury trial|waive', ''),
        ('privacy', 'Do you acknowledge the privacy policy / certify your answers?', r'privacy (policy|notice)|certify|acknowledge|attest|i agree',
         'Yes'),
    ]
    return [{"key": k, "question": q, "pattern": pat, "answer": a, "source": "profile"} for k, q, pat, a in rows] + regions.answer_rows(p)


def _tokens(s):
    return {w for w in re.findall(r'[a-z0-9]+', (s or '').lower()) if w not in STOP and len(w) > 1}


# Questions with no single right answer ("What interested you in CFS?", "Anything else?"): the agent writes these per job.
OPEN_ENDED = re.compile(r'\bwhy\b|interest(ed|s)? (you|in)|what (draws|drew|attracts|excites|motivates)|tell us (about|why|what)|'
                        r'\bdescribe\b|\bexplain\b|cover letter|anything else|additional (information|comments)|what makes you|'
                        r'how (would|will|do) you|share (a|an|your|any)|in your own words|\bmotivat|what do you hope|'
                        r'what are you (looking|hoping)|walk us through|\bessay\b', re.I)

WRITE_RULES = (
    "Write this one yourself, for this job only. Read the posting (applytwin_get_job) and the user's vault. "
    "2-4 sentences and under 90 words unless the form asks for more; stay under any character limit. First person, plain words, "
    "the way a sharp student writes in five minutes. Name one specific thing about this company or role from the posting and tie "
    "it to one real thing the user did, with its real numbers. Do not restate the question, do not open with 'I am excited', "
    "'passionate' or 'thrilled', no 'not only X but Y' or 'it's not X, it's Y', no em or en dashes, no list of three, no closing line "
    "that sums up, no buzzwords (leverage, cutting-edge, innovative, synergy, dynamic, journey, impactful). Never invent "
    "experience, interests or facts. Do not save it with applytwin_save_answer: it is specific to this company.")


def open_ended(question):
    return bool(OPEN_ENDED.search(question or ''))


# Facts nobody but the user has: never filled from a near match (a recommender's name is not the user's name). Only an
# answer the user saved for this question is used; otherwise the agent asks, or leaves an optional field blank.
NEVER_GUESS = re.compile(r'date of birth|birth ?date|\bdob\b|social security|\bssn\b|'
                         r'\b(recommender|referrer|referee|reference|emergency contact|supervisor|employee who referred|person who referred)'
                         r'[^?]{0,25}\b(name|e-?mail|phone|contact|title)\b|'
                         r'\b(name|e-?mail|phone)\b[^?]{0,25}\b(recommender|referrer|referee|reference|emergency contact|supervisor|'
                         r'employee who referred|person who referred|who referred)|^\s*who referred you', re.I)
ASK_HOW = ("Only the user knows this. Never guess or reuse another answer. If the field is optional, leave it blank; if it is "
           "required, applytwin_notify the user and log Needs User with this exact question.")

# "How did you hear about us?" options differ on every form: the closest truthful one (the role was found on the company's
# own careers site or a job board), never "Referral" or "Career fair"
HEAR_PICKS = [r'company (careers? )?(web)?site|careers? (site|page|website)|company website|(our|corporate) website', r'^website$|web ?site',
              r'job board|online job|internet|online|web search|search engine|google', r'job (site|posting)|posting', r'^other\b']


def match(question, bank, options=None, context=None):
    """Best answer for one question. options = the dropdown/radio choices, if any (we pick the closest). context = facts
    about this job's company from ApplyTwin's own records: {company, worked_here, applied_before, country, home}. country
    is where the job is, home the user's main country (the UK by default): a right-to-work or sponsorship question that
    names no country is answered for the job's country, or for home when the user has answered for it."""
    ctx = context or {}
    r = _match(question, bank, options, ctx.get('country') or ctx.get('home') or regions.HOME, bool(ctx.get('country')))
    return _finish(r, bank, options, context or {})


DATE_KEYS = ('grad', 'start', 'school_start', 'grad_year')


def date_formats(text):
    """'May 2029' in the shapes forms ask for. Month and year only: a day of the month is never made up."""
    m = re.search(r'\b(' + '|'.join(x[:3] for x in MONTHS) + r')[a-z]*\.?\s+(20\d\d)\b', text or '', re.I)
    if not m:
        y = re.search(r'\b(20\d\d)\b', text or '')
        return {"year": y.group(1)} if y else {}
    mi = [x[:3].lower() for x in MONTHS].index(m.group(1).lower()[:3]) + 1
    y = m.group(2)
    return {"month": MONTHS[mi - 1], "month_number": f'{mi:02d}', "year": y, "MM/YYYY": f'{mi:02d}/{y}', "YYYY-MM": f'{y}-{mi:02d}',
            "Month YYYY": f'{MONTHS[mi - 1]} {y}', "note": "If the form needs a day of the month, use the one the user gave; never pick one."}


def _finish(r, bank, options, ctx):
    k = r.get('key')
    vals = {row.get('key'): row.get('answer') for row in bank}
    if k == 'prior_employee' and 'worked_here' in ctx and r.get('confidence', 0) >= 0.9 and not _user_saved(bank, k):
        # the vault lists every place the user worked: "No" is only true when this company isn't one of them
        a = 'Yes' if ctx['worked_here'] else 'No'
        r.update(answer=pick_option(a, options) if options else a, confidence=0.92)
    if k == 'applied_before' and r.get('answer') in (None, '') and ctx.get('applied_before'):
        r.update(answer=pick_option('Yes', options) if options else 'Yes', confidence=0.92)
        r.pop('action', None)
    if k in ('grad', 'grad_year') and options:
        year, month = str(vals.get('grad_year') or ''), (vals.get('grad') or '').split(' ')[0] if vals.get('grad') else ''
        if year and not any(year in (o or '') for o in options):
            why = blockers.grad_options_knockout(options, year, month)
            other = next((o for o in options if re.search(r'\bother\b|not listed', o or '', re.I)), None)
            if why:
                return {"question": r['question'], "answer": None, "confidence": 0.95, "key": k, "action": "knockout",
                        "skip_reason": why, "how": "The form's own graduation options exclude the user: log Skipped with skip_reason."}
            if other:
                r.update(answer=other, confidence=0.9)
                r['how'] = f"The user's graduation ({vals.get('grad') or year}) isn't listed: chose '{other}'. Type the real date if it asks."
            else:
                r.update(answer=None, confidence=0, action=f"none of the options is {vals.get('grad') or year}: never pick a different "
                                                           "year; leave it for the user (Needs User with the exact options)")
    if k in DATE_KEYS and r.get('answer'):
        f = date_formats(vals.get('grad') if k == 'grad_year' else r['answer'])
        if f:
            r['formats'] = f
    if not options and isinstance(r.get('answer'), str):
        r['answer'] = nodash(r['answer'])   # typed text never carries an en or em dash; a listed option is kept exactly
    return r


def _user_saved(bank, key):
    return any(row.get('key') == key and row.get('source') == 'user' for row in bank)


def _match(question, bank, options=None, country=None, strict=False):
    q = (question or '').strip()
    # "Why ...?", "Describe ...", "Tell us ...": always written for the job, even when a word inside ("major", "relocate")
    # would match a saved fact
    if re.match(r'\s*(why|please (describe|explain|tell)|describe|explain|tell us|what (interest|excite|draw|motivat))', q, re.I) and open_ended(q) \
            and not re.search(r'linkedin|github|portfolio|website|url|link|race|ethnic|gender|veteran|disab|authori[sz]|sponsor|visa|citizen', q, re.I):
        return {"question": q, "answer": None, "confidence": 0, "key": None, "action": "write", "how": WRITE_RULES}
    intl = regions.match(q, bank, options, country, strict)   # right to work in the UK / EU / India (never the US answer), notice period, GDPR...
    if intl:
        return intl
    if not options and NEVER_GUESS.search(q):
        qt = _tokens(q)
        for row in bank:
            if row.get('source') == 'user' and row.get('answer') not in (None, '') and (
                    (row.get('question') or '').strip().lower() == q.lower() or
                    qt and len(qt & _tokens(row.get('question'))) / len(qt | _tokens(row.get('question'))) >= 0.6):
                return {"question": q, "answer": row['answer'], "confidence": 0.9, "key": row.get('key')}
        if re.search(r'referr', q, re.I) and next((r.get('answer') for r in bank if r.get('key') == 'referral'), '') == 'No':
            return {"question": q, "answer": None, "confidence": 0.9, "key": 'referral',
                    "action": "leave it blank: the user was not referred (if the form requires it, type N/A)"}
        return {"question": q, "answer": None, "confidence": 0, "key": None, "action": "ask the user, then applytwin_save_answer",
                "how": ASK_HOW}
    k = {r.get('key'): r.get('answer') for r in bank}
    special = _derived(q, k, options)
    if special:
        return special
    if re.search(r'authori[sz]ed|eligible|permitted', q, re.I) and re.search(r'sponsor', q, re.I) and k.get('work_auth') and k.get('sponsorship'):
        # "authorized to work WITHOUT sponsorship": yes only if both are true
        both = k['work_auth'] == 'Yes' and k['sponsorship'] == 'No'
        ans = 'Yes' if both else 'No'
        return {"question": q, "answer": pick_option(ans, options) if options else ans, "confidence": 0.9, "key": 'work_auth'}
    best, conf = None, 0.0
    for row in bank:
        pat = row.get('pattern')
        if pat:
            try:
                if re.search(pat, q, re.I):
                    best, conf = row, 0.92
                    break
            except re.error:
                pass
    if best is not None and best.get('answer') in (None, '') and best.get('key') != 'arbitration':
        # the profile field is blank, but the user may have saved this same question in their own words
        qt = _tokens(q)
        for row in bank:
            if row.get('source') == 'user' and row.get('answer') not in (None, ''):
                rt = _tokens(row.get('question'))
                if qt and rt and len(qt & rt) / len(qt | rt) >= 0.5:
                    best = row
                    break
    if not best:
        qt = _tokens(q)
        for row in bank:
            rt = _tokens(row.get('question'))
            if not qt or not rt:
                continue
            j = len(qt & rt) / len(qt | rt)
            if j > conf:
                best, conf = row, j
        conf = min(0.85, conf * 1.3)
    if (not best or conf < 0.92) and open_ended(q):   # nothing saved fits exactly: write it for this job
        return {"question": q, "answer": None, "confidence": 0, "key": None, "action": "write", "how": WRITE_RULES}
    if not best or conf < 0.45 or best.get('answer') in (None, ''):
        return {"question": q, "answer": None, "confidence": round(conf, 2), "key": best.get('key') if best else None,
                "action": "ask the user, then applytwin_save_answer"}
    ans = best['answer']
    if options and best.get('key') == 'hear' and best.get('source') != 'user':
        opts = [o for o in options if o and o.strip().lower() not in ('select', 'select one', '--', 'please select')]
        hit = next((o for pat in HEAR_PICKS for o in opts if re.search(pat, o.strip(), re.I)), None)
        return {"question": q, "answer": hit, "confidence": round(conf, 2) if hit else 0, "key": 'hear',
                **({} if hit else {"action": "pick the closest truthful option by hand (where the posting was found); never "
                                             "'Referral' or 'Career fair' unless the user said so"})}
    if options and best.get('key') in EEO_KEYS:
        hit = eeo_option(best.get('key'), ans, options)
        if hit is None:
            return {"question": q, "answer": None, "confidence": 0.3, "key": best.get('key'), "user_value": ans,
                    "action": f"no option clearly matches '{ans}'. Pick the one that is still true by hand, or the decline option "
                              f"only if the user chose to decline; otherwise Needs User with the options."}
        return {"question": q, "answer": hit, "confidence": round(conf, 2), "key": best.get('key')}
    if options and best.get('key') in STRICT_KEYS:
        hit = pick_strict(ans, options, best.get('key'))
        if hit is None:
            return {"question": q, "answer": None, "confidence": 0.3, "key": best.get('key'), "user_value": ans,
                    "action": f"no option is '{ans}'. Pick the closest BROAD option that is still true (e.g. 'Engineering', "
                              f"'Other') by hand; never a different specific one (Computer Engineering is not Computer Science "
                              f"or Aerospace Engineering). If none is true, Needs User with the options."}
        return {"question": q, "answer": hit, "confidence": round(conf, 2), "key": best.get('key')}
    if options:
        ans = pick_option(ans, options)
    return {"question": q, "answer": ans, "confidence": round(conf, 2), "key": best.get('key')}


PARENTS = re.compile(r'\b(parents?|carers?|guardians?|mother|father)\b[^?]{0,60}\b(attend\w*|go to|went to|been to|have|has|hold|holds|'
                     r'complete\w*|obtain\w*|gone to)\b[^?]{0,40}\b(university|higher education|(a |an )?(undergraduate |university )?degree)', re.I)
CLASS_RANK = [(r'\bfirst\b|\b1st\b', 4), (r'upper second|\b2[:.]1\b', 3), (r'lower second|\b2[:.]2\b', 2), (r'\bthird\b|\b3rd\b', 1)]
CLASS_BAR = re.compile(r'(?:at least|minimum(?: of)?|achieve|on track for|predicted|expected)?\s*(?:a\s+)?(first|1st|upper second|2[:.]1|lower second|2[:.]2|third|3rd)'
                       r'(?:[^?]{0,25}\b(or (above|higher|better|equivalent)|and above|minimum))', re.I)


def _rank(text):
    return next((r for pat, r in CLASS_RANK if re.search(pat, text or '', re.I)), None)


def _derived(q, k, options):
    '''Answers computed from a saved one: "Did your parents go to university?" is the opposite of first-generation; "Do you
    have (or expect) a 2:1 or above?" compares the user's class with the bar. None when it doesn't apply.'''
    def res(key, a):
        return {"question": q, "answer": pick_option(a, options) if options else a, "confidence": 0.9, "key": key}
    if PARENTS.search(q) and not re.search(r'first[- ](generation|in)', q, re.I):
        fg = (k.get('first_generation') or '').strip()
        if fg in ('Yes', 'No'):
            return res('first_generation', 'No' if fg == 'Yes' else 'Yes')
        if fg and DECLINE_RX.search(fg):
            return res('first_generation', fg)
        return {"question": q, "answer": None, "confidence": 0.9, "key": 'first_generation',
                "action": "ask the user (whether their parents went to university), then applytwin_save_answer"}
    m = CLASS_BAR.search(q)
    if m and re.match(r'\s*(do|did|will|are|have|is|can)\b', q, re.I):
        mine, bar = _rank(k.get('degree_class')), _rank(m.group(1))
        if mine is None:
            return {"question": q, "answer": None, "confidence": 0.9, "key": 'degree_class',
                    "action": "ask the user (their predicted or achieved degree class against this bar), then applytwin_save_answer"}
        return res('degree_class', 'Yes' if mine >= bar else 'No')
    return None


STRICT_KEYS = ('major', 'school', 'degree')
GENERIC = {'of', 'and', 'in', 'the', 'science', 'sciences', 'studies', 'arts', 'bachelor', 'bachelors', 'degree', 'university', 'college',
           'engineering', 'program', 's'}
DEGREE_SYN = [(r"\bbachelor|\bb\.?\s?s\.?c?\b|\bb\.?a\.?\b|\bb\.?eng\b|undergrad", 'bachelor'), (r"\bmaster|\bm\.?s\.?c?\b|\bm\.?eng\b", 'master'),
              (r'\bph\.?d|doctor', 'phd'), (r'\bassociate', 'associate'), (r'\bmba\b', 'mba')]


def _deg(s):
    return next((v for pat, v in DEGREE_SYN if re.search(pat, s or '', re.I)), None)


def pick_strict(answer, options, key):
    """School, major and degree: the exact option or a broader true one, never a sibling ('Aerospace Engineering' for
    'Computer Engineering' was a real mis-pick). None when nothing fits."""
    a = (answer or '').strip()
    opts = [o for o in options if o and o.strip().lower() not in ('select', 'select one', '--', 'please select', '')]
    low = a.lower()
    for o in opts:
        if o.strip().lower() == low:
            return o
    if key == 'degree':
        d = _deg(a)
        hits = [o for o in opts if d and _deg(o) == d]
        if hits:   # "Bachelor of Science" -> "Bachelor's Degree"; prefer the one naming the same field (Science/Arts)
            return max(hits, key=lambda o: len(_tokens(o) & _tokens(a)))
        return None
    at = _tokens(a)
    within = [o for o in opts if low in o.lower()]   # "Computer Engineering" in "Electrical and Computer Engineering"
    if within:
        return min(within, key=len)
    covers = [o for o in opts if at and at <= _tokens(o)]   # every word of the answer, generic ones too
    if covers:
        return min(covers, key=len)
    if key == 'school':
        abbrev = [o for o in opts if re.sub(r'[^a-z]', '', o.lower()) and len(o) <= 6 and
                  re.sub(r'[^a-z]', '', o.lower()) == ''.join(w[0] for w in re.findall(r'[a-z]+', low) if w not in ('of', 'and', 'the'))]
        return abbrev[0] if abbrev else None
    broad = [o for o in opts if _tokens(o) and _tokens(o) <= (_tokens(a) | {'other'}) and not (_tokens(o) - GENERIC - {'other'})]
    return min(broad, key=lambda o: 'other' in o.lower()) if broad else None


DECLINE_RX = re.compile(r"prefer not|decline|do not (want|wish) to (answer|disclose|say)|don'?t (want|wish) to (answer|disclose|say)|"
                        r"rather not|not to (answer|disclose|say)|choose not", re.I)
EEO_KEYS = ('race', 'veteran', 'gender')
_RACE_GROUP = [('mixed', r'mixed|two or more|multiple|multi-?racial'), ('asian', r'\basian\b'), ('black', r'\bblack\b|african'),
               ('white', r'\bwhite\b'), ('hispanic', r'hispanic|latin[oax]'), ('arab', r'\barab\b'),
               ('native', r'american indian|alaska native|native hawaiian|pacific islander')]


def _race_group(text):
    return next((g for g, pat in _RACE_GROUP if re.search(pat, text or '', re.I)), None)


def eeo_option(key, answer, options):
    '''The form's option for a saved gender, ethnicity or veteran answer, translating between UK and US categories
    ("Mixed: White and Asian" -> "Two or more races", "Man" -> "Male"). None when no option is clearly the same.'''
    a = (answer or '').strip()
    opts = [o for o in options if o and o.strip().lower() not in ('select', 'select one', '--', 'please select', '')]
    exact = next((o for o in opts if o.strip().lower() == a.lower()), None)
    if exact:
        return exact
    if DECLINE_RX.search(a):
        return next((o for o in opts if DECLINE_RX.search(o)), None)
    low = a.lower()
    if key == 'gender':
        syn = {'man': r'^\s*(male|man)\b', 'male': r'^\s*(male|man)\b', 'woman': r'^\s*(female|woman)\b', 'female': r'^\s*(female|woman)\b',
               'non-binary': r'non[- ]?binary', 'prefer to self-describe': r'self[- ]describe|not listed|another'}.get(low)
        return next((o for o in opts if syn and re.search(syn, o, re.I)), None)
    if key == 'race':
        g = _race_group(a)
        if g in (None, 'arab'):   # "Arab", "any other ethnic group": the US and UK lists differ; the user decides
            return None
        cands = [o for o in opts if _race_group(o) == g]
        if g == 'white':
            cands = [o for o in cands if not re.search(r'mixed|two or more|\band\b', o, re.I)]
        if not cands:
            return None
        at = _tokens(a)
        score = {o: len(at & _tokens(o)) for o in cands}
        top = max(score.values())
        best = [o for o in cands if score[o] == top]
        # one clear option, or one that names the user's own subgroup; "Asian" against "...: Indian" / "...: Chinese" is
        # not the user's answer to pick for them
        return best[0] if len(best) == 1 else None
    if key == 'veteran':
        us_form = any(re.search(r'protected veteran', o, re.I) for o in opts)
        if low == 'no' or re.search(r'not (a )?(protected )?veteran|have not served', low):
            pat = r'not a (protected )?veteran|i am not|^no\b|have not served|not served|never served'
        elif 'us protected veteran' in low:
            pat = r'identify as one or more|^(yes|i am a (protected )?veteran)|protected veteran(?!.*\bnot\b)'
            return next((o for o in opts if re.search(pat, o, re.I) and not re.search(r'\bnot\b', o, re.I)), None)
        elif 'uk armed forces' in low:
            if us_form:   # a UK veteran is not a US "protected veteran", but whether to say so is the user's call
                return None
            pat = r'^yes|have served|served in|veteran|armed forces'
            return next((o for o in opts if re.search(pat, o, re.I) and not NEG.search(o)), None)
        else:
            return pick_option(a, opts) if _tokens(a) & set().union(*[_tokens(o) for o in opts]) else None
        return next((o for o in opts if re.search(pat, o, re.I)), None)
    return None


NEG = re.compile(r"\b(no|not|don'?t|do not|never|without|none|n/a)\b", re.I)


def pick_option(answer, options):
    """Map a free answer onto the closest of the form's options (Yes -> 'Yes, I am authorized...')."""
    a = (answer or '').lower().strip()
    opts = [o for o in options if o and o.lower() not in ('select', 'select one', '--', 'please select')]
    for o in opts:
        if o.lower() == a:
            return o
    if DECLINE_RX.search(a):   # "Prefer not to say" -> "Decline to self-identify" / "I do not want to answer"
        hit = next((o for o in opts if DECLINE_RX.search(o)), None)
        if hit:
            return hit
    if a in ('yes', 'no'):
        for o in opts:
            if re.match(r'^%s\b' % a, o.lower()):
                return o
        # 'I will not require sponsorship' / 'I will require sponsorship': the negated one is No
        neg = [o for o in opts if NEG.search(o)]
        if len(opts) == 2 and len(neg) == 1:
            return neg[0] if a == 'no' else next(o for o in opts if o is not neg[0])
    at = _tokens(a)
    scored = sorted(opts, key=lambda o: -len(at & _tokens(o)) / (len(_tokens(o)) or 1))
    return scored[0] if scored and at & _tokens(scored[0]) else answer


def upsert(bank, question, answer, key=None):
    key = key or re.sub(r'[^a-z0-9]+', '_', question.lower())[:40]
    for row in bank:
        if row.get('key') == key or row.get('question', '').lower() == question.lower():
            row['answer'] = answer
            row['source'] = 'user'
            return bank
    bank.append({"key": key, "question": question, "pattern": None, "answer": answer, "source": "user"})
    return bank


# ------------------------------------------------------------------ the questions every application asks

YES_NO = ['Yes', 'No']
MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
DECLINE = 'Prefer not to say'
UK_RIGHTS = [{"value": "citizen", "label": "British or Irish citizen, settled / pre-settled status or ILR"},
             {"value": "authorized", "label": "I have a visa that lets me work (e.g. Graduate, Skilled Worker)"},
             {"value": "sponsorship", "label": "I would need the employer to sponsor a visa"}]
QUESTIONS = [   # (key, label, group, kind, options, optional, hint)  ... kind: text | yesno | select. 'eeo.x' / 'work_auth.X' keys are nested.
    # Set up for the UK first; the US-only questions sit in their own optional group at the end.
    ('name', 'Full name', 'You', 'text', None, False, ''),
    ('email', 'Email', 'You', 'text', None, False, ''),
    ('phone', 'Phone', 'You', 'text', None, False, '+44 7700 900123'),
    ('location', 'Where you live', 'You', 'text', None, False, 'Town or city, e.g. Manchester'),
    ('address', 'Street address', 'You', 'text', None, False, '12 High Street'),
    ('address2', 'Flat, suite or unit', 'You', 'text', None, True, 'Flat 4B'),
    ('postal_code', 'Postcode', 'You', 'text', None, False, 'SW1A 1AA'),
    ('country', 'Country', 'You', 'text', None, False, 'United Kingdom'),
    ('linkedin', 'LinkedIn', 'You', 'text', None, True, 'linkedin.com/in/...'),
    ('github', 'GitHub', 'You', 'text', None, True, ''),
    ('website', 'Website or portfolio', 'You', 'text', None, True, ''),
    ('school', 'University', 'Education', 'text', None, False, ''),
    ('degree', 'Degree', 'Education', 'select', ['BSc (Bachelor of Science)', 'BA (Bachelor of Arts)', 'BEng (Bachelor of Engineering)',
                                                 "MEng (integrated master's)", "MSci (integrated master's)", 'LLB (Bachelor of Laws)',
                                                 'MA (Scottish undergraduate)', 'MSc', 'MA', 'MRes', 'MBA', 'PhD', 'Degree apprenticeship',
                                                 'Foundation degree', 'HND', 'Other'], False, ''),
    ('major', 'Degree subject', 'Education', 'text', None, False, 'e.g. Computer Science'),
    ('minor', 'Second subject (joint honours or minor)', 'Education', 'text', None, True, ''),
    ('degree_class', "Degree classification (predicted if you haven't finished)", 'Education', 'select',
     ['First (1st)', 'Upper second (2:1)', 'Lower second (2:2)', 'Third (3rd)', 'Distinction', 'Merit', 'Pass', 'Not a UK-style degree'],
     False, ''),
    ('a_levels', 'A-level grades (or equivalent)', 'Education', 'text', None, False, 'e.g. A*AA in Maths, Further Maths, Physics (or IB 38)'),
    ('ucas_points', 'UCAS tariff points', 'Education', 'text', None, True, 'e.g. 152'),
    ('gcse', 'GCSE results (or equivalent)', 'Education', 'text', None, True, 'e.g. 9 GCSEs at 9-7, including Maths and English'),
    ('gpa', 'GPA or grade average, if your university gives one', 'Education', 'text', None, True, 'Leave blank to never share it'),
    ('grad_month', 'Graduation month', 'Education', 'select', MONTHS, False, ''),
    ('grad_year', 'Graduation year', 'Education', 'text', None, False, ''),
    ('class_standing', 'Year of study right now', 'Education', 'select', UK_YEARS + ['Placement year', "Master's", 'PhD', 'Graduated'] + US_YEARS,
     False, 'Freshman to Senior are for US universities'),
    ('enrolled', 'Currently studying for a degree', 'Education', 'yesno', YES_NO, False, ''),
    ('earliest_start', 'Earliest start date', 'Education', 'text', None, False, 'e.g. September 2027'),
    # optional, but forms ask them often enough that a blank one sent applications to "Needs you" in real runs
    ('start_month', 'Month you started university', 'Education', 'select', MONTHS, True, ''),
    ('start_year', 'Year you started university', 'Education', 'text', None, True, '2025'),
    ('school_email', 'University email', 'Education', 'text', None, True, 'you@university.ac.uk'),
    ('availability', 'Dates you are free for an internship or placement', 'Education', 'text', None, True, '16 June - 5 September 2027'),
    ('high_school', 'School or sixth form you attended', 'Education', 'text', None, True, ''),
    ('hs_grad_year', 'Year you left school or sixth form', 'Education', 'text', None, True, ''),
    ('work_auth.GB', 'Right to work in the UK', 'Right to work', 'select', UK_RIGHTS, False,
     'On a Student or Graduate visa? Most graduate jobs will need sponsorship later'),
    ('nationality', 'Nationality', 'Right to work', 'text', None, False, 'e.g. British'),
    ('willing_to_relocate', 'Willing to relocate', 'Right to work', 'yesno', YES_NO, False, ''),
    ('onsite_ok', 'Able to work on-site or hybrid', 'Right to work', 'yesno', YES_NO, False, ''),
    ('over_18', 'At least 18 years old', 'Standard questions', 'yesno', YES_NO, False, ''),
    ('background_check_ok', 'Consent to background and vetting checks (e.g. DBS, BPSS)', 'Standard questions', 'yesno', YES_NO, False, ''),
    ('has_noncompete', 'Bound by a non-compete or non-solicitation clause', 'Standard questions', 'yesno', YES_NO, False, ''),
    ('government_employee', 'Current or former civil servant or government employee', 'Standard questions', 'yesno', YES_NO, False, ''),
    ('knows_employee', 'Know someone or have relatives working at companies you apply to', 'Standard questions', 'yesno', YES_NO, True,
     'Answer No only if that is true everywhere; otherwise leave blank and you are asked per company'),
    ('offers', 'Other offers or recruiting deadlines right now', 'Standard questions', 'text', None, True, 'e.g. No'),
    ('notice_period', 'Notice period', 'Standard questions', 'text', None, True, 'e.g. None (student) or 1 month'),
    ('sms_ok', 'Happy for recruiters to text you', 'Standard questions', 'yesno', YES_NO, False, ''),
    ('ai_review_ok', 'Happy for companies to use AI to review your application', 'Standard questions', 'yesno', YES_NO, False, ''),
    ('salary_expectation', 'Salary expectations', 'Standard questions', 'text', None, False, 'e.g. Flexible, in line with the advertised range'),
    ('eeo.gender', 'Gender', 'Equality monitoring', 'select', ['Man', 'Woman', 'Non-binary', 'Prefer to self-describe', DECLINE], False, ''),
    ('eeo.race', 'Ethnic group', 'Equality monitoring', 'select',
     ['Asian or Asian British: Indian', 'Asian or Asian British: Pakistani', 'Asian or Asian British: Bangladeshi',
      'Asian or Asian British: Chinese', 'Asian or Asian British: any other Asian background',
      'Black, Black British, Caribbean or African: African', 'Black, Black British, Caribbean or African: Caribbean',
      'Black, Black British, Caribbean or African: any other Black background',
      'Mixed or multiple ethnic groups: White and Black Caribbean', 'Mixed or multiple ethnic groups: White and Black African',
      'Mixed or multiple ethnic groups: White and Asian', 'Mixed or multiple ethnic groups: any other mixed background',
      'White: English, Welsh, Scottish, Northern Irish or British', 'White: Irish', 'White: Gypsy or Irish Traveller', 'White: Roma',
      'White: any other White background', 'Other ethnic group: Arab', 'Other ethnic group: any other ethnic group', DECLINE], False,
     'UK Census (ONS) groups'),
    ('eeo.disability', 'Disability (as defined by the Equality Act 2010)', 'Equality monitoring', 'select', ['No', 'Yes', DECLINE], False, ''),
    ('eeo.sexual_orientation', 'Sexual orientation', 'Equality monitoring', 'select',
     ['Heterosexual or straight', 'Gay or lesbian', 'Bisexual', 'Other sexual orientation', DECLINE], True, ''),
    ('eeo.religion', 'Religion or belief', 'Equality monitoring', 'select',
     ['No religion', 'Buddhist', 'Christian', 'Hindu', 'Jewish', 'Muslim', 'Sikh', 'Any other religion', DECLINE], True, ''),
    ('eeo.school_type', 'Type of school you mainly attended aged 11-16', 'Equality monitoring', 'select',
     ['State-run or state-funded school (non-selective)', 'State-run or state-funded school (selective on academic, faith or other grounds)',
      'Independent or fee-paying school', 'Independent or fee-paying school, with a means-tested bursary covering 90% or more of the fees',
      'Attended school outside the UK', "Don't know", DECLINE], True, 'Social mobility monitoring'),
    ('eeo.free_school_meals', 'Eligible for free school meals at any point during school', 'Equality monitoring', 'select',
     ['Yes', 'No', 'Not applicable (finished school before 1980 or went to school overseas)', "Don't know", DECLINE], True, ''),
    ('eeo.first_generation', 'First in your immediate family to go to university', 'Equality monitoring', 'select',
     ['Yes', 'No', "Don't know", DECLINE], True, ''),
    ('eeo.veteran', 'Served in the armed forces', 'Equality monitoring', 'select',
     ['No', 'Yes, in the UK Armed Forces', 'Yes, I am a US protected veteran', DECLINE], True, ''),
    ('eeo.pronouns', 'Pronouns', 'Equality monitoring', 'text', None, True, 'Optional'),
    # US forms only: blank is fine unless you apply to jobs in the US
    ('work_authorized_us', 'Legally authorised to work in the US', 'US applications only', 'yesno', YES_NO, False, ''),
    ('needs_sponsorship', 'Will need US visa sponsorship, now or later', 'US applications only', 'yesno', YES_NO, False, ''),
    ('citizenship', 'US citizenship status', 'US applications only', 'select',
     ['U.S. citizen', 'U.S. permanent resident (green card)', 'Authorized to work, not a citizen or permanent resident',
      'Need sponsorship (F-1, H-1B, etc.)', 'Not a U.S. citizen or resident', 'Prefer not to say'], True, 'Only used when a US form asks'),
    ('eeo.hispanic', 'Hispanic or Latino (US forms)', 'US applications only', 'select', ['Yes', 'No', 'Decline to self-identify'], True, ''),
    ('political_contributions', 'Made political contributions over $150 in the last 2 years (US finance forms)', 'US applications only',
     'yesno', YES_NO, True, ''),
    ('sat_score', 'SAT score', 'US applications only', 'text', None, True, 'Leave blank if you never share it'),
    ('act_score', 'ACT score', 'US applications only', 'text', None, True, 'Leave blank if you never share it'),
]


def get(p, key):
    if '.' in key:   # 'eeo.gender', 'work_auth.GB'
        a, b = key.split('.', 1)
        return (p.get(a) or {}).get(b, '')
    return p.get(key)


# Required only for users who apply in that country: UK questions when the UK is among their countries (the default for
# new profiles), US work authorisation when the US is (or when no countries are picked: the US-first setup).
WHEN = {'work_auth.GB': 'GB', 'nationality': 'GB', 'degree_class': 'GB', 'a_levels': 'GB',
        'work_authorized_us': 'US', 'needs_sponsorship': 'US'}


def applies(key, p):
    """Whether a question is needed for this user (see WHEN)."""
    when = WHEN.get(key)
    if not when:
        return True
    cs = regions.targets(p or {})[0]
    return when in cs or (when == 'US' and not cs)


def gaps(p):
    """Required questions with no answer yet: [{key, label, group}]. Blank never gets guessed; the user is asked."""
    return [{"key": k, "label": l, "group": g} for k, l, g, kind, opts, optional, hint in QUESTIONS
            if not optional and applies(k, p) and get(p, k) in (None, '')]


def questions():
    # when: 'GB' / 'US' = required only for users applying there (the app checks it against their countries)
    return [{"key": k, "label": l, "group": g, "kind": kind, "options": opts, "optional": optional, "hint": hint, "when": WHEN.get(k)}
            for k, l, g, kind, opts, optional, hint in QUESTIONS]
