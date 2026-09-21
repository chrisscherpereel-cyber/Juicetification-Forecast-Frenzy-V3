APP_KEY="fcst"; NAME="Forecast Frenzy"; SCHEMA_VERSION=1
MANIFEST={"app_key":APP_KEY,"name":NAME,"schema_version":SCHEMA_VERSION,"params":{
  "price":{"type":"float","default":6.00,"min":0,"group":"Economics","label":"Price per drink"},
  "var_cost":{"type":"float","default":2.25,"min":0,"group":"Economics","label":"Variable cost per drink"},
  "fruit_prep_cost":{"type":"float","default":1.10,"min":0,"group":"Economics","label":"Fruit prep cost"},
  "bottle_cost":{"type":"float","default":1.60,"min":0,"group":"Economics","label":"Bottle cost"},
  "wage_per_hr":{"type":"float","default":16.00,"min":0,"group":"Economics","label":"Wage per hour"},
  "shift_hours":{"type":"int","default":8,"min":1,"max":24,"group":"Economics","label":"Shift hours"},
  "service_per_emp":{"type":"int","default":22,"min":1,"group":"Economics","label":"Customers/employee/hour"},
  "promo_cost":{"type":"float","default":60.0,"min":0,"group":"Events","label":"Promo cost"},
  "promo_lift":{"type":"float","default":0.15,"min":0,"max":1,"group":"Events","label":"Promo demand lift"},
  "satisfaction_penalty":{"type":"float","default":0.75,"min":0,"group":"Events","label":"Stockout penalty"},
  "base_demand":{"type":"int","default":320,"min":1,"group":"Demand","label":"Base daily demand"},
  "growth_per_day":{"type":"float","default":0.0040,"min":0,"max":0.02,"group":"Demand","label":"Demand growth per day (trend)"},
  "completion_salt":{"type":"str","default":"forecast-frenzy-2026","group":"Admin","label":"Completion-code secret"},
}}
