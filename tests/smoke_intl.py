"""International smoke checks. Run from tests/smoke.py (shares its `res`, `ok`, `api`, `store`, `render`), or alone:
python3 tests/smoke_intl.py"""
import json as _json
import os as _os
_os.environ.setdefault('APPLYTWIN_NO_TWIN', '1')   # never open or reach the real twin browser
_os.environ.setdefault('APPLYTWIN_SCAN_INLINE', '1')   # scans stay in-process so tests can stand in for them
import re as _re
import sys as _sys
import tempfile as _tf
import time

if 'res' not in globals():   # standalone: a throwaway home and the same helpers smoke.py has
    _os.environ.setdefault('APPLYTWIN_NO_TELEMETRY', '1')
    _os.environ.setdefault('APPLYTWIN_NO_AGENT', '1')
    _os.environ['APPLYTWIN_NO_NOTIFY'] = '1'   # no desktop notifications
    _os.environ['APPLYTWIN_HOME'] = _tf.mkdtemp(prefix='applytwin-intl-')
    ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    _sys.path.insert(0, ROOT)
    from applytwin import api, render, store  # noqa: F401
    store.save('resume.json', _json.load(open(_os.path.join(ROOT, 'examples', 'resume.example.json'), encoding='utf-8')))
    res = []
    ok = lambda c, m: print(('PASS ' if c else 'FAIL ') + m) or c
    _standalone = True
else:
    _standalone = False

from applytwin import answers as _ans, match as _m, regions as _rg  # noqa: E402

# location parsing: international formats
_cases = {
    'Bengaluru/Bangalore': ('IN', 'Bengaluru'), 'Hybrid, London': ('GB', 'London'), 'London, UK': ('GB', 'London'),
    'IN-KA-Bengaluru': ('IN', 'Bengaluru'), 'Amsterdam, North Holland, Netherlands': ('NL', 'Amsterdam'), 'Berlin, DE': ('DE', 'Berlin'),
    'Wilmington, DE': ('US', None), 'Cambridge, MA': ('US', None), 'London, ON': ('CA', None), 'Gurugram, HARYANA, India': ('IN', 'Delhi NCR'),
    'München': ('DE', 'Munich'), 'Zürich, Switzerland': ('CH', 'Zurich'), 'Dublin, CA': ('US', None), 'GBR - LON Metro': ('GB', None),
    'United Kingdom, London, London': ('GB', 'London'), 'Athens, Georgia': ('US', None), 'Remote (UK)': ('GB', None),
    'Madrid, ES': ('ES', 'Madrid'), 'Bengaluru, KA, India': ('IN', 'Bengaluru'), 'Santa Clara, CA': ('US', None),
}
_bad = {k: (p['country'], p['city']) for k, want in _cases.items() for p in [_rg.parse(k)[0]] if (p['country'], p['city']) != want}
_emea = _rg.parse('Remote - EMEA')[0]
_multi = _rg.countries('Berlin; Munich; Paris') == {'DE', 'FR'} and [p['city'] for p in _rg.parse('Hyderabad/Bangalore')] == ['Hyderabad', 'Bengaluru']
res.append(ok(bool(not _bad and _emea['group'] == 'emea' and _emea['remote'] and _multi),
              f'location parsing: cities, country codes, "Bengaluru/Bangalore", "Remote - EMEA", "Hybrid, London" {_bad}'))

# region filtering respects the countries and cities picked
_P = {'grad_year': '2028', 'grad_month': 'May', 'degree': 'BS Computer Science',
      'search': {'kind': 'internship', 'roles': ['software engineer'], 'countries': ['United Kingdom', 'India'], 'cities': ['London', 'Bangalore']},
      'work_auth': {'GB': 'sponsorship', 'IN': 'citizen'}}
_J = lambda t, l, d='': {'title': t, 'location': l, 'description': d, 'company': 'Example', 'source': 'greenhouse'}
_uk, _wuk = _m.fit(_J('Software Engineer Intern', 'London, United Kingdom'), _P)
_mcr, _ = _m.fit(_J('Software Engineer Intern', 'Manchester, England'), _P)
_de, _wde = _m.fit(_J('Software Engineer Intern', 'Berlin, Germany'), _P)
_us, _ = _m.fit(_J('Software Engineer Intern', 'New York, NY'), _P)
_rem, _ = _m.fit(_J('Software Engineer Intern', 'Remote - EMEA'), _P)
_blr, _ = _m.fit(_J('SDE Intern', 'Bengaluru/Bangalore'), _P)
_legacy = {'search': {'kind': 'internship', 'roles': ['software engineer'], 'locations': ['United States']}}
_lus = _m.fit(_J('Software Engineer Intern', 'Austin, TX'), _legacy)[0] > 0 and _m.fit(_J('Software Engineer Intern', 'London, UK'), _legacy)[0] == 0
res.append(ok(bool(_uk > _mcr > 0 and 'London' in _wuk and _de == 0 and 'Germany' in _wde and _us == 0 and _rem > 0 and _blr > 0 and _lus),
              f'region filter: UK/India picked -> London {_uk} > Manchester {_mcr}, Berlin and New York skipped, Remote EMEA kept; US-only users unchanged'))

# local program names: placement year, Werkstudent, PPO; and the program types a user picks
_pl = _m.fit(_J('Software Engineering Placement Year 2027/28', 'Bristol, UK'), _P)
_ws = dict(_P, search=dict(_P['search'], countries=['Germany'], cities=[], programs=['internship']))
_wsk = _m.fit(_J('Werkstudent Softwareentwicklung (m/w/d)', 'Berlin, Germany', 'software engineer'), _ws)
_ws2 = dict(_ws, search=dict(_ws['search'], programs=['internship', 'working_student']))
_wsk2 = _m.fit(_J('Werkstudent Software Engineering (m/w/d)', 'Berlin, Germany'), _ws2)
_ppo = _m.fit(_J('SDE Intern (PPO)', 'Hyderabad, India'), _P)
res.append(ok(bool(_pl[0] > 0 and 'placement' in _pl[1] and _wsk[0] == 0 and 'program' in _wsk[1] and _wsk2[0] > 0 and 'PPO' in _ppo[1]),
              f'programs: placement year and Werkstudent count as internships, PPO noted, unpicked program types skipped ({_wsk[1]})'))

# work authorization knockouts per country
_rtw = 'You must have the right to work in the UK. Unfortunately we are unable to offer visa sponsorship.'
_k1 = _m.knockouts(_J('Software Engineer Intern', 'London, UK', _rtw), _P)
_k2 = _m.knockouts(_J('SDE Intern', 'Bengaluru, India', 'We do not offer visa sponsorship.'), _P)   # an Indian citizen in India
_P3 = dict(_P, work_auth={})
_k3 = _m.knockouts(_J('Software Engineer Intern', 'London, UK', _rtw), _P3)   # status not given: never skipped
_f3 = _m.fit(_J('Software Engineer Intern', 'London, UK', _rtw), _P3)
_usp = {'needs_sponsorship': True, 'search': {}, 'work_auth': {'GB': 'citizen'}}   # needs US sponsorship, British citizen
_k4 = _m.knockouts(_J('Software Engineer Intern', 'London, UK', 'We do not offer visa sponsorship.'), _usp)
_k5 = _m.knockouts(_J('Software Engineer Intern', 'Austin, TX', 'We will not sponsor visas for this role.'), _usp)
_eu = dict(_P, search=dict(_P['search'], countries=['Germany']), work_auth={'EU': 'sponsorship'})
_k6 = _m.knockouts(_J('Werkstudent Data (m/w/d)', 'Munich, Germany', 'EU citizens only.'), _eu)
res.append(ok(bool(_k1 and 'UK' in _k1[0] and not _k2 and not _k3 and 'Settings' in _f3[1] and not _k4 and _k5 and _k6 and 'EU' in _k6[0]),
              f'work rights: UK no-sponsorship skips a user who needs it ({_k1[:1]}), never skips unknown status, US rules only for US jobs'))

# international application answers: per-country right to work, never the US answer for a UK question; ask when blank
_prof = {'name': 'Asha Rao', 'nationality': 'India', 'work_authorized_us': False, 'needs_sponsorship': True,
         'work_auth': {'GB': 'sponsorship', 'IN': 'citizen', 'EU': 'authorized'}, 'search': {'countries': ['GB', 'IN', 'DE']},
         'notice_period': 'Immediately', 'phone': '+91 98765 43210'}
_bank = _ans.default_bank(_prof)
_q = lambda q, o=None: _ans.match(q, _bank, o)
_a = {k: _q(k) for k in ('Do you have the right to work in the UK?', 'Will you require visa sponsorship to work in the United Kingdom?',
                         'Are you authorised to work in Germany without sponsorship?', 'Do you have the right to work in India?',
                         'What is your notice period?', 'What is your expected CTC (in LPA)?', 'Do you consent to the processing of your personal data (GDPR)?',
                         'What is your nationality?', 'Are you an Indian citizen?', 'Phone country code', 'What were your 10th grade marks?',
                         'Are you legally authorized to work in the United States?')}
_opt = _q('Do you have the right to work in the UK?', ['Yes, I have the right to work in the UK', 'No, I will require sponsorship'])
_v = [_a[k]['answer'] for k in _a]
res.append(ok(bool(_v == ['No', 'Yes', 'Yes', 'Yes', 'Immediately', None, 'Yes', 'India', 'Yes', '+91 (India)', None, 'No']
              and _a['What is your expected CTC (in LPA)?']['action'].startswith('ask') and _opt['answer'].startswith('No')),
              f'international answers: UK/EU/India right to work, notice period, GDPR, nationality; CTC and marks asked, not invented ({_v})'))

# CV conventions: A4 + "CV" outside the US/Canada, CGPA label for India; Letter + "Resume" in the US
_cuk, _cin, _cus = _rg.conventions('GB'), _rg.conventions('India'), _rg.conventions('US')
_res_in = {'education': [{'school': 'IIT Bombay', 'gpa': '8.7'}]}
_rg.apply_conventions(_res_in, {'location': 'Mumbai, India'})
res.append(ok(bool(_cuk['doc'] == 'CV' and _cuk['paper'] == 'A4' and not _cuk['photo'] and _cin['gpa_label'] == 'CGPA' and _cus['paper'] == 'Letter'
              and _cus['doc'] == 'Resume' and _res_in['paper'] == 'A4' and _res_in['education'][0]['gpa'] == '8.7/10'
              and _rg.file_label({'location': 'London, UK'}) == 'CV' and _rg.format_date('2027-05-15', 'GB') == '15/05/2027'),
              'CV conventions: UK/EU/India A4 + CV + no photo, CGPA out of 10 in India, US Letter + Resume, local date order'))

# an A4 CV renders on exactly one A4 page
_v4 = api.get_vault()
_v4 = dict(_v4, paper='A4')
_out = _os.path.join(store.path('resumes', 'a4test'), 'Test_CV.pdf')
_r4 = render.render(_v4, 'classic', _out)
_raw = open(_out, 'rb').read()
_mb = _re.search(rb'/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)', _raw)
_size = (round(float(_mb.group(1))), round(float(_mb.group(2)))) if _mb else None
res.append(ok(bool(_r4['pages'] == 1 and _size == (595, 842) and 'size: A4' in render.build_html(_v4) and 'size: A4' in render.build_html(api.get_vault())
              and 'size: A4' not in render.build_html(dict(_v4, paper='Letter'))),
              f'A4 rendering: one page, {_size} pt (A4 = 595x842); A4 by default, US jobs Letter'))

# UK first: defaults, UK questions, and a right-to-work question that names no country answered for the job's country
from applytwin import store as _st  # noqa: E402
_ukp = {'work_auth': {'GB': 'sponsorship'}, 'work_authorized_us': True, 'needs_sponsorship': False, 'class_standing': 'Second year',
        'degree_class': 'Upper second (2:1)', 'grad_year': '2099', 'a_levels': 'A*AA', 'eeo': {'disability': 'Prefer not to say', 'school_type': 'Independent or fee-paying school'}}
_ukb = _ans.default_bank(_ukp)
_uka = lambda q, ctx=None, opts=None: _ans.match(q, _ukb, opts, ctx or {}).get('answer')
_uk_cases = {
    ('Are you legally authorised to work in the country this role is based in?', 'GB'): 'No',     # the UK answer for a London job
    ('Will you require visa sponsorship?', 'GB'): 'Yes',
    ('Will you require visa sponsorship?', 'US'): 'No',                                              # a US job keeps the US answer
    ('Are you authorized to work in the US?', 'GB'): 'Yes',                                          # names the US: the US answer
    ('What year of study are you currently in?', None): 'Second year',
    ('What is your predicted degree classification?', None): 'Upper second (2:1)',
    ('Is your degree classification predicted or achieved?', None): 'Predicted',
    ('Please list your A-level grades', None): 'A*AA',
    ('What type of school did you attend between the ages of 11 and 16?', None): 'Independent or fee-paying school',
}
_ukbad = {q: _uka(q, {'country': c} if c else {}) for (q, c), want in _uk_cases.items() if _uka(q, {'country': c} if c else {}) != want}
_dis = _uka('Do you have a disability?', None, ['No, I do not have a disability', 'Yes, I have a disability', 'I do not want to answer'])
_qkeys = {q["key"] for q in _ans.questions()}
res.append(ok(bool(not _ukbad and _dis == 'I do not want to answer' and _rg.conventions()['doc'] == 'CV' and _rg.conventions()['paper'] == 'A4'
                   and _rg.format_date('2027-05-15') == '15/05/2027' and _st.DEFAULT_PROFILE['search']['countries'] == ['United Kingdom']
                   and _rg.home({}) == 'GB' and {'work_auth.GB', 'degree_class', 'a_levels', 'eeo.school_type'} <= _qkeys
                   and _ans.standing({'class_standing': 'Second year'})[1] == 'Going into third year'
                   and _rg.program('Spring Week 2027 - Markets') == 'internship' and _rg.gpa_label({'gpa': '2:1 (predicted)'}) == 'Grade'
                   and _rg.resume_region({'location': 'Manchester, UK'}) == 'uk'),
              f'UK first: CV/A4/DD-MM by default, UK questions, generic right-to-work answered for the job country {_ukbad or ""} {_dis}'))

# review fixes: monitoring answers map UK <-> US categories truthfully (or ask), derived answers, narrow patterns
_USR = ['American Indian or Alaska Native', 'Asian', 'Black or African American', 'Native Hawaiian or Other Pacific Islander', 'White',
        'Two or more races', 'Decline to self-identify']
_USV = ['I am not a protected veteran', 'I identify as one or more of the classifications of protected veteran', "I don't wish to answer"]
_eq = lambda key, val, q, opts: _ans.match(q, _ans.default_bank({'eeo': {key: val}}), opts).get('answer')
_eeo_cases = [
    (('veteran', 'Yes, I am a US protected veteran', 'Veteran status', _USV), 'I identify as one or more of the classifications of protected veteran'),
    (('veteran', 'No', 'Veteran status', _USV), 'I am not a protected veteran'),
    (('veteran', 'Yes, in the UK Armed Forces', 'Veteran status', _USV), None),                    # the user's call, not a guess
    (('race', 'Mixed or multiple ethnic groups: White and Asian', 'Race', _USR), 'Two or more races'),
    (('race', 'Other ethnic group: Arab', 'Race', _USR), None),
    (('race', 'White: Irish', 'Race', _USR), 'White'),
    (('race', 'Asian', 'Ethnic group', ['Asian or Asian British: Indian', 'Asian or Asian British: Chinese', 'White: British']), None),
    (('gender', 'Man', 'Gender', ['Male', 'Female', 'Decline to self-identify']), 'Male'),
    (('gender', 'Prefer not to say', 'Gender', ['Male', 'Female', 'Decline to self-identify']), 'Decline to self-identify'),
]
_eeobad = [(c, _eq(*c)) for c, want in _eeo_cases if _eq(*c) != want]
_rp = {'eeo': {'religion': 'Christian', 'first_generation': 'No'}, 'degree_class': 'Upper second (2:1)', 'grad_year': '2026', 'grad_month': 'June',
       'major': 'Physics', 'degree': 'BSc (Bachelor of Science)', 'gpa': '2:1', 'location': 'Leeds, UK', 'class_standing': 'Second year',
       'needs_sponsorship': False, 'work_auth': {'GB': 'sponsorship'}}
_rb = _ans.default_bank(_rp)
_ra = lambda q, opts=None, ctx=None: _ans.match(q, _rb, opts, ctx or {}).get('answer')
_rcases = [
    (('Did either of your parents attend university?', ['Yes', 'No']), 'Yes'),     # not first generation -> parents did
    (('Are you willing to work on religious holidays?', ['Yes', 'No']), None),
    (('Religion or belief', None), 'Christian'),
    (('Job classification', ['Full-time', 'Part-time']), None),
    (('Do you have a 2:1 or above?', ['Yes', 'No']), 'Yes'),
    (('Do you expect a First or above?', ['Yes', 'No']), 'No'),
    (('Current stage of application', None), None),
    (('Degree subject', None), 'Physics'),
    (('What is your GPA?', None), None),                                             # a UK class is not a GPA
    (('County', None), None),                                                       # "Leeds, UK": the UK is not a county
]
_rbad = [(c, _ra(*c)) for c, want in _rcases if _ra(*c) != want]
_kind = _ans.class_kind({'degree_class': 'First (1st)', 'grad_year': str(time.gmtime().tm_year - 1), 'grad_month': 'June'})
_h1b = _ans.match('Will you require H-1B sponsorship?', _rb, None, {'country': 'GB'}).get('answer')   # a US visa: the US answer
_us_user = {'search': {'countries': ['United States']}}
_usgaps = {g['key'] for g in _ans.gaps(_us_user)}
from applytwin.importer import profile_from_resume as _pfr  # noqa: E402
_pc = lambda loc, gpa='': _pfr({'basics': {'location': loc}, 'education': [{'school': 'X', 'gpa': gpa}]}, {})
_imp_bad = {l: _pc(l).get('country') for l, want in {'Cambridge, Massachusetts': None, 'London, Ontario': None, 'Birmingham, Alabama': None,
                                                     'Leeds, UK': 'United Kingdom', 'Manchester': 'United Kingdom'}.items()
            if (_pc(l).get('country') if _pc(l).get('country') != 'United States' else None) != want}
_imp_cls = _pc('Leeds, UK', '2:1 (predicted)')
res.append(ok(bool(not _eeobad and not _rbad and not _imp_bad and _imp_cls.get('degree_class') == 'Upper second (2:1)' and not _imp_cls.get('gpa') and _kind == 'Achieved' and _h1b == 'No'
                   and _rg.resume_region({'location': 'Remote'}, _us_user) is None and _rg.file_label({'location': 'Remote'}, _us_user) == 'Resume'
                   and _rg.conventions(None, _us_user)['paper'] == 'Letter' and _rg.home({'search': {'countries': []}}) == 'US'
                   and not {'degree_class', 'a_levels', 'work_auth.GB', 'nationality'} & _usgaps
                   and {'work_authorized_us', 'needs_sponsorship'} <= _usgaps
                   and not {'work_authorized_us', 'needs_sponsorship'} & {g['key'] for g in _ans.gaps({'search': {'countries': ['United Kingdom']}})}
                   and _rg.program('Customer Insight Programme Manager') == '' and _rg.program('Spring Insight Programme 2027') == 'internship'),
              f'review fixes: EEO UK<->US mapping {_eeobad}, derived and narrow answers {_rbad}, importer {_imp_bad}, US users keep US conventions and gaps'))

if _standalone:
    print(f'\n{sum(res)}/{len(res)} passed')
    _sys.exit(0 if all(res) else 1)
