import requests
import json

r = requests.get('http://127.0.0.1:8011/api/v1/analytics/dashboard')
data = r.json()

print('All metrics:')
for m in data['metrics']:
    print(f'  - {m["name"]}: {m["value"]} {m["unit"]}')

print('\nCohort analysis available:', 'cohort_analysis' in data)
if 'cohort_analysis' in data and data['cohort_analysis']:
    print('Cohort data points:', len(data['cohort_analysis']['d7_d14_cohorts']))
else:
    print('No cohort data')

print('\nSystem health:', data.get('system_health', {}))
