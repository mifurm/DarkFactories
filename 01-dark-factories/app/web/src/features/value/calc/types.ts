export type Scenario = 'conservative' | 'base' | 'upside'
export type OverrideValue = number | number[] | null
export type Overrides = Record<string, OverrideValue>

export type Driver = {
  id: string
  label: string
  group: string
  unit: string
  kind: 'number' | 'nullable' | 'list' | 'pairs'
  base: unknown
  low: unknown
  high: unknown
  min: number | null
  max: number | null
  flag: string
  source: string
  scenario: Record<Scenario, unknown>
  scenario_driver: boolean
  editable: boolean
  length?: number
  detail?: string
}
export type Group = { id: string; label: string; kind: 'core' | 'expansion' | 'prices'; drivers: Driver[] }
export type Switch = { lever: string; key: string; group: string; label: string; off: number; on: number; scenario: Record<Scenario, number>; min: number; max: number }

export type Headline = {
  npv: number
  roi_pct: number
  payback_months: number | null
  irr_pct: number | null
  acr_year3: number
  acr_run_rate: number
  acr_per_plant_year: number
  expansion_npv: number
  expansion_acr_year3: number
  expansion_acr_run_rate: number
  fleet_plants: number
  fleet_acr_run_rate_core: number
  fleet_acr_run_rate_expansion: number
}
export type Meta = {
  meta: { name: string; assumptions_version: string; model_version: string; currency: string; horizon_years: number; reference_customer: string }
  scenarios: Scenario[]
  groups: Group[]
  switches: Switch[]
  counts: { drivers: number; prices: number }
  reference: { model_version: string; headline: Record<Scenario, Headline> }
  price_basis: { basis: string; retrieved_on: string; currency: string }
}

export type Tier = { id: string; label: string; plants: number; assets_per_plant: number; total: number; per_plant: number; pull_through_ratio: number }
export type ExpansionTier = {
  id: string
  label: string
  plants: number
  assets_per_plant: number
  without_levers: { total: number; per_plant: number; per_asset_year: number }
  with_levers: { total: number; per_plant: number; per_asset_year: number }
  uplift_multiple: number
}
export type LeverRow = {
  id: string
  label: string
  note: string
  adoption: number
  start_lag_months: number
  deploying_plants_at_full_rollout: number
  per_deploying_plant: { azure_run_cost: number; other_run_cost: number; benefit: number; net: number; one_time_cost: number; payback_months: number | null; benefit_to_run_cost_ratio: number | null }
  enterprise_fixed: { azure_run_cost_at_reference_scale: number; other_run_cost: number; one_time_cost: number }
  npv: number
  run_rate: { azure: number; azure_per_deploying_plant: number }
}
export type LineItem = { id: string; family: string; item: string; kind: string; quantity: number; unit: string; unit_price: number; annual: number; lever: string }
export type Sens = { id: string; label: string; swing: number }
export type NpvSens = Sens & { npv_low: number; npv_high: number }
export type AcrSens = Sens & { acr_year3_low: number; acr_year3_high: number; base_value: unknown }

export type Calc = {
  scenario: string
  model_version: string
  horizon_years: number
  benefits: { by_category: Record<string, number[]>; category_labels: Record<string, string>; total_by_year: number[]; total: number }
  costs: { azure_by_family: Record<string, number[]>; family_labels: Record<string, string>; total_by_year: number[]; total: number }
  roi: { net_benefit_by_year: number[]; cumulative: number[]; npv: number; discount_rate: number; roi_pct: number; payback_months: number | null; irr_pct: number | null }
  acr: {
    by_year: number[]
    by_family: Record<string, number[]>
    run_rate_by_family: Record<string, number>
    by_lever: Record<string, number[]>
    run_rate_by_lever: Record<string, number>
    lever_adoption: Record<string, number>
    run_rate_year3: number
    per_plant_year: number
    tiers: Tier[]
    pull_through_ratio: number
    line_items: LineItem[]
  }
  levers: LeverRow[]
  memo: { five_year: { npv: number; roi_pct: number } }
  expansion: {
    case: string
    adoption: Record<string, number>
    headline: { npv: number; npv_5yr: number; roi_pct: number; payback_months: number | null; acr_year3: number; acr_run_rate: number; acr_per_plant_year: number }
    levers: LeverRow[]
    tiers: ExpansionTier[]
    path: { id: string; label: string; value: number; kind: 'total' | 'delta' }[]
  }
  sensitivity?: NpvSens[]
  acr_sensitivity?: AcrSens[]
}

/** Tornado data arrives on a slower path than the headline numbers (it re-runs the model ~30 times). */
export type SensResult = { key: string; npv: number; acr3: number; npvItems: NpvSens[]; acrItems: AcrSens[] }
