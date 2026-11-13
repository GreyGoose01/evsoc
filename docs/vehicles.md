# Supported vehicles

Generated with `evsoc models --markdown`. Do not edit by hand.

**270 profiles** (abrp: 18, evsoc: 17, obdb: 165, wican: 70), **72 makes**. In addition, `evsoc_generic_obd` tries the standardised OBD values on every car (PID 5B, 9A, B2, D2 and UDS F45B/F4B2), which many hybrids and all new US electric cars from 2026/27 provide.

"all models" means: commands that OBDb lists for all models of a make (mostly hybrids).
The Platform column shows shared technology; `evsoc read --car` automatically tries all profiles of the same platform.

## Abarth

| Model | Platform | Profiles |
|---|---|---|
| 500e (2023-) |  | `evsoc_fiat_500e_2020` |

## Acura

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_acura` |

## Aiways

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_aiways` |
| U5 (2019-2023) |  | `obdb_aiways_u5` |
| U5 (2020-) |  | `abrp_u5` |

## Alfa Romeo

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_alfa_romeo` |
| Junior (2024-) | Stellantis e-CMP / STLA Small | `evsoc_stellantis_ecmp` |

## Audi

| Model | Platform | Profiles |
|---|---|---|
| A3 (1996-) |  | `obdb_audi_a3` |
| A7 (2010-) |  | `obdb_audi_a7` |
| all models |  | `obdb_audi` |
| e tron (2019-2025) | Audi MLB evo e-tron | `obdb_audi_e_tron` |
| Q4 e tron (2021-) | VW MEB | `obdb_audi_q4_e_tron` |
| Q4 e-tron (2021-) | VW MEB | `abrp_meb` |
| Q4 e-tron / Q4 Sportback e-tron (2021-) | VW MEB | `evsoc_vw_meb` |
| Q7 (2006-) |  | `obdb_audi_q7` |

## Bentley

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_bentley` |

## BMW

| Model | Platform | Profiles |
|---|---|---|
| 225xe / 330e / 530e / X1 25e / X5 40e (F series, experimental) (2015-2019) | BMW i3 | `evsoc_bmw_sme` |
| 3 Series (1975-) |  | `obdb_bmw_3_series` |
| 5 Series (1972-) |  | `obdb_bmw_5_series` |
| 7 Series (1977-) |  | `obdb_bmw_7_series` |
| all models |  | `obdb_bmw` |
| i3 | BMW i3 | `wican_bmw_i3` |
| i3 (2013-2022) | BMW i3 | `obdb_bmw_i3` |
| i3 / i3s (2013-2022) | BMW i3 | `evsoc_bmw_sme` |
| i3s (2018-2022) | BMW i3 | `obdb_bmw_i3s` |
| i4 (G26, derived) (2021-) | BMW Gen5 eDrive | `evsoc_bmw_gen5` |
| i5 (2023-) | BMW Gen5 eDrive | `evsoc_bmw_gen5` |
| i5 (2024-) | BMW Gen5 eDrive | `obdb_bmw_i5` |
| i7 (derived) (2022-) | BMW Gen5 eDrive | `evsoc_bmw_gen5` |
| iX (derived) (2021-) | BMW Gen5 eDrive | `evsoc_bmw_gen5` |
| iX3 (2020-2024) | BMW Gen5 eDrive | `obdb_bmw_ix3` |
| iX3 (G08) (2020-2025) | BMW Gen5 eDrive | `evsoc_bmw_gen5` |
| X1 (2009-) |  | `obdb_bmw_x1` |
| X5 (1999-) |  | `obdb_bmw_x5` |

## Buick

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_buick` |

## BYD

| Model | Platform | Profiles |
|---|---|---|
| Atto 2/Atto 3/Yuan Plus EV/Dolphin/Seal/Seal U/Sealion/M6/eMax 7/海豚/Denza D9/Denza N7/Sealion 7 EV (EU version, only before 2024.10 update) | BYD e-Platform 3.0 | `wican_byd_atto_2_atto_3_yuan_plus_ev_dolphin_seal_seal_u_sealion_m6_emax_7_denza_d9_denza_n7_sealion_7_ev_eu_version_only_before_2024_10_update` |
| Atto 3 | BYD e-Platform 3.0 | `wican_byd_atto_3` |
| Dolphin/Shark | BYD e-Platform 3.0 | `wican_byd_dolphin_shark` |
| Seal | BYD e-Platform 3.0 | `wican_byd_seal` |

## Cadillac

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_cadillac` |
| LYRIQ (2023-) | GM Ultium / BEV3 | `obdb_cadillac_lyriq` |

## Chevrolet

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_chevrolet` |
| Bolt | GM Bolt / Ampera-e | `wican_chevrolet_bolt` |
| Bolt EUV (2022-2023) | GM Bolt / Ampera-e | `obdb_chevrolet_bolt_euv` |
| Bolt EV (2017-) | GM Bolt / Ampera-e | `obdb_chevrolet_bolt_ev` |
| Bolt EV (2017-2018) | GM Bolt / Ampera-e | `abrp_bolt17` |
| Bolt EV (2019-) | GM Bolt / Ampera-e | `abrp_bolt19` |
| Equinox EV (2024-) | GM Ultium / BEV3 | `obdb_chevrolet_equinox_ev` |
| Spark EV (2014-2016) | GM Bolt / Ampera-e | `abrp_bolt17` |
| Volt (2011-2019) | GM Voltec | `obdb_chevrolet_volt` |
| Volt/Ampera | GM Voltec | `wican_chevrolet_volt_ampera` |

## Chrysler

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_chrysler` |
| Pacifica 2015+ |  | `wican_chrysler_pacifica_2015` |

## Citroen

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_citroen` |
| C-Zero | Mitsubishi i-MiEV family | `wican_citroen_c_zero` |
| C5 Aircross Hybrid (experimental) (2020-) | Stellantis EMP2 Plug-in-Hybrid | `evsoc_stellantis_phev` |
| e-Berlingo / e-Jumpy / e-SpaceTourer (2020-) | Stellantis e-CMP / STLA Small | `evsoc_stellantis_ecmp` |
| e-C4 / e-C4 X (2020-) | Stellantis e-CMP / STLA Small | `evsoc_stellantis_ecmp` |
| eC4 X (2022-) | Stellantis e-CMP / STLA Small | `obdb_citroen_ec4_x` |
| ë-C3 / e-C3 / ë-C3 Aircross (experimental) (2024-) | Stellantis Smart Car | `evsoc_stellantis_smartcar` |

## Cupra

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_cupra` |
| Born / Tavascan (2021-) | VW MEB | `abrp_meb`, `evsoc_vw_meb` |
| Formentor (2020-) |  | `obdb_cupra_formentor` |

## Dacia

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_dacia` |
| Spring/CITY K-ZE | Dacia Spring | `wican_dacia_spring_city_k_ze` |

## Daihatsu

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_daihatsu` |

## Datsun

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_datsun` |

## Deepal

| Model | Platform | Profiles |
|---|---|---|
| S05 (2025-) |  | `abrp_deepal_s05` |

## Dodge

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_dodge` |

## DS

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_ds` |
| DS 3 E-Tense (2019-) | Stellantis e-CMP / STLA Small | `evsoc_stellantis_ecmp` |
| DS 7 E-Tense (experimental) (2019-) | Stellantis EMP2 Plug-in-Hybrid | `evsoc_stellantis_phev` |

## Fiat

| Model | Platform | Profiles |
|---|---|---|
| 500e (2012-) |  | `obdb_fiat_500e` |
| 500e (332) (2020-) |  | `evsoc_fiat_500e_2020` |
| 600e | Stellantis e-CMP / STLA Small | `wican_fiat_600e` |
| 600e (2023-) | Stellantis e-CMP / STLA Small | `evsoc_stellantis_ecmp` |
| all models |  | `obdb_fiat` |
| e-Doblo (2022-) | Stellantis e-CMP / STLA Small | `evsoc_stellantis_ecmp` |
| e-Ulysse | Stellantis EMP2 Van (eK9) | `wican_fiat_e_ulysse` |
| e-Ulysse / E-Scudo (2022-) | Stellantis e-CMP / STLA Small | `evsoc_stellantis_ecmp` |
| Grande Panda Elettrica (derived, experimental) (2025-) | Stellantis Smart Car | `evsoc_stellantis_smartcar` |

## Ford

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_ford` |
| Edge (2007-2024) |  | `obdb_ford_edge` |
| Explorer EV / Capri (2024-) | VW MEB | `abrp_meb`, `evsoc_vw_meb` |
| F 150 Lightning (2022-2025) | Ford GE1 (Mach-E) | `obdb_ford_f_150_lightning` |
| F-150 PowerBoost Hybrid (experimental) (2021-) |  | `evsoc_ford_hybrid_pt` |
| Focus Electric (2012-2018) |  | `obdb_ford_focus_electric` |
| Focus RS (MK3) |  | `wican_ford_focus_rs_mk3` |
| Fusion Hybrid (2010-2020) |  | `obdb_ford_fusion_hybrid` |
| Maverick (2022-) |  | `obdb_ford_maverick` |
| Maverick / Escape / Kuga Hybrid and PHEV (experimental) (2021-) |  | `evsoc_ford_hybrid_pt` |
| Mondeo (1993-) |  | `obdb_ford_mondeo` |
| Mustang Mach E (2021-) | Ford GE1 (Mach-E) | `obdb_ford_mustang_mach_e` |
| Mustang Mach-E (2021-) | Ford GE1 (Mach-E) | `abrp_mache` |
| Transit (1965-) |  | `obdb_ford_transit` |
| Transit North America 2022 |  | `wican_ford_transit_north_america_2022` |

## Geely

| Model | Platform | Profiles |
|---|---|---|
| EX5 (2024-) | Volvo/Geely (CMA, SPA, SEA) | `evsoc_geely_becm` |
| EX5 2026 | Volvo/Geely (CMA, SPA, SEA) | `wican_geely_ex5_2026` |
| Geometry C | Volvo/Geely (CMA, SPA, SEA) | `wican_geely_geometry_c` |

## Genesis

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_genesis` |
| GV60 (2021-) | Hyundai/Kia E-GMP | `abrp_ioniq5` |
| GV60 (2022-) | Hyundai/Kia E-GMP | `obdb_genesis_gv60` |
| GV60/GV70 EV/G80 Electrified | Hyundai/Kia E-GMP | `wican_genesis_gv60_gv70_ev_g80_electrified` |

## GM

| Model | Platform | Profiles |
|---|---|---|
| Hummer EV, Silverado EV, Sierra AV; BEV3: Cadillac Lyriq, Celestiq, Chevrolet Blazer EV, Equinox EV; Honda Prologue EV; Acura ZDX | GM Ultium / BEV3 | `wican_bt1_hummer_ev_silverado_ev_sierra_av_bev3_cadillac_lyriq_celestiq_chevrolet_blazer_ev_equinox_ev_honda_prologue_ev_acura_zdx` |

## GMC

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_gmc` |
| Sierra EV | GM Ultium / BEV3 | `wican_gmc_sierra_ev` |

## GWM

| Model | Platform | Profiles |
|---|---|---|
| Ora Good Cat/Funky Cat/ES11/Haomao/Ora 03 |  | `wican_gwm_ora_good_cat_funky_cat_es11_haomao_ora_03` |

## Haval

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_haval` |
| Jolion HEV (2021-) |  | `obdb_haval_jolion_hev` |

## Holden

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_holden` |

## Honda

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_honda` |
| Civic (1972-) |  | `obdb_honda_civic` |
| Clarity-2018 |  | `wican_honda_clarity_2018` |
| CR V Hybrid (2017-) |  | `obdb_honda_cr_v_hybrid` |
| CR Z (2010-2016) |  | `obdb_honda_cr_z` |
| e:Ny1 (2023-) |  | `abrp_eny1` |
| Fit (2001-) |  | `obdb_honda_fit` |
| Prologue | GM Ultium / BEV3 | `wican_honda_prologue` |

## Hyundai

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_hyundai` |
| Elantra (1990-) |  | `obdb_hyundai_elantra` |
| Ioniq 5 (2021-) | Hyundai/Kia E-GMP | `abrp_ioniq5` |
| IONIQ 5 (2021-) | Hyundai/Kia E-GMP | `obdb_hyundai_ioniq_5` |
| Ioniq 6 (2022-) | Hyundai/Kia E-GMP | `abrp_ioniq5` |
| IONIQ 6 (2022-) | Hyundai/Kia E-GMP | `obdb_hyundai_ioniq_6` |
| Ioniq Electric (2016-2018) | Hyundai/Kia gen 1 | `abrp_hkmc2017` |
| IONIQ Electric (2016-2022) | Hyundai/Kia gen 1 | `obdb_hyundai_ioniq_electric` |
| Ioniq Electric (2019-2022) | Hyundai/Kia gen 1 | `abrp_hkmc2019` |
| Ioniq Electric 38kWh (2020-2021) (2020-2021) | Hyundai/Kia gen 1 | `wican_hyundai_ioniq_electric_38kwh_2020_2021` |
| Ioniq Hybrid EV (2016-2019) (2016-2019) | Hyundai/Kia gen 1 | `wican_hyundai_ioniq_hybrid_ev_2016_2019` |
| IONIQ PlugIn Hybrid (2017-2022) | Hyundai/Kia gen 1 | `obdb_hyundai_ioniq_plugin_hybrid` |
| Ioniq2017 |  | `wican_hyundai_ioniq2017` |
| Ioniq5/Ioniq6 (2021-2024) (2021-2024) | Hyundai/Kia E-GMP | `wican_hyundai_ioniq5_ioniq6_2021_2024` |
| Ioniq5/Ioniq6 72kWh | Hyundai/Kia E-GMP | `wican_hyundai_ioniq5_ioniq6_72kwh` |
| Ioniq5/Ioniq6 77kWh (2021-2024) (2021-2024) | Hyundai/Kia E-GMP | `wican_hyundai_ioniq5_ioniq6_77kwh_2021_2024` |
| Ioniq9 | Hyundai/Kia E-GMP | `wican_hyundai_ioniq9` |
| Kona | Hyundai/Kia gen 1 | `wican_hyundai_kona` |
| Kona (2017-) | Hyundai/Kia gen 1 | `obdb_hyundai_kona` |
| Kona Electric (2018-) | Hyundai/Kia gen 1 | `abrp_hkmc2019`, `obdb_hyundai_kona_electric` |
| Palisade (2018-) |  | `obdb_hyundai_palisade` |
| Santa Fe Hybrid (2020-) |  | `obdb_hyundai_santa_fe_hybrid` |
| Veloster (2011-2022) |  | `obdb_hyundai_veloster` |

## Infiniti

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_infiniti` |

## Jaguar

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_jaguar` |
| E PACE (2017-) |  | `obdb_jaguar_e_pace` |
| I PACE (2018-2024) |  | `obdb_jaguar_i_pace` |
| I-PACE | Jaguar I-Pace | `wican_jaguar_i_pace` |
| I-Pace (2018-2020) | Jaguar I-Pace | `abrp_ipace2019` |
| I-Pace (2021-) | Jaguar I-Pace | `abrp_ipace2021` |

## Jeep

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_jeep` |
| Avenger (2023-) | Stellantis e-CMP / STLA Small | `evsoc_stellantis_ecmp` |

## KGM (SsangYong)

| Model | Platform | Profiles |
|---|---|---|
| Torres EVX |  | `wican_kgm_torres_evx` |

## Kia

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_kia` |
| e-Niro (2018-2022) | Hyundai/Kia gen 1 | `abrp_hkmc2019` |
| e-Soul (2019-) | Hyundai/Kia gen 1 | `abrp_hkmc2019` |
| EV3 (2024-) | Hyundai/Kia gen 1 | `obdb_kia_ev3` |
| EV6 | Hyundai/Kia E-GMP | `wican_kia_ev6` |
| EV6 (2021-) | Hyundai/Kia E-GMP | `abrp_ioniq5`, `obdb_kia_ev6` |
| EV6 77kWh | Hyundai/Kia E-GMP | `wican_kia_ev6_77kwh` |
| EV9 (2023-) | Hyundai/Kia E-GMP | `obdb_kia_ev9` |
| Niro (2016-) | Hyundai/Kia gen 1 | `obdb_kia_niro` |
| Niro EV | Hyundai/Kia gen 1 | `wican_kia_niro_ev` |
| Niro EV (2018-) | Hyundai/Kia gen 1 | `obdb_kia_niro_ev` |
| Niro PHEV | Hyundai/Kia gen 1 | `wican_kia_niro_phev` |
| Niro/Soul | Hyundai/Kia gen 1 | `wican_kia_niro_soul` |
| Seltos (2019-) |  | `obdb_kia_seltos` |
| Sorento (2002-) |  | `obdb_kia_sorento` |
| Sportage (1993-) |  | `obdb_kia_sportage` |
| Sportage HEV (2022-) |  | `obdb_kia_sportage_hev` |

## Lamborghini

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_lamborghini` |

## Lancia

| Model | Platform | Profiles |
|---|---|---|
| Ypsilon (2024-) | Stellantis e-CMP / STLA Small | `evsoc_stellantis_ecmp` |

## Land Rover

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_land_rover` |
| Defender (1983-) |  | `obdb_land_rover_defender` |

## Lexus

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_lexus` |
| RX (1999-) |  | `obdb_lexus_rx` |

## Lincoln

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_lincoln` |

## Lotus

| Model | Platform | Profiles |
|---|---|---|
| all models | Volvo/Geely (CMA, SPA, SEA) | `obdb_lotus` |
| Eletre / Emeya (derived) (2023-) | Volvo/Geely (CMA, SPA, SEA) | `evsoc_geely_becm` |

## Lynk & Co

| Model | Platform | Profiles |
|---|---|---|
| 01 / 08 PHEV (derived) (2020-) | Volvo/Geely (CMA, SPA, SEA) | `evsoc_geely_becm` |

## Maserati

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_maserati` |

## Maxus

| Model | Platform | Profiles |
|---|---|---|
| T90/EUNIC5/EUNIC6/EUNIC9/EV30/EG10/eDeliver3/eDeliver9 |  | `wican_maxus_t90_eunic5_eunic6_eunic9_ev30_eg10_edeliver3_edeliver9` |

## Mazda

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_mazda` |
| CX 30 (2020-) |  | `obdb_mazda_cx_30` |
| CX 50 (2023-) |  | `obdb_mazda_cx_50` |
| EZ-6/6e |  | `wican_mazda_ez_6_6e` |
| MX 30 (2020-) |  | `obdb_mazda_mx_30` |

## Mercedes-Benz

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_mercedes_benz` |
| EQA (2021-) |  | `evsoc_mercedes_mfa2`, `obdb_mercedes_benz_eqa` |
| EQB (2021-) | Mercedes MFA2 | `evsoc_mercedes_mfa2` |

## MG

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_mg` |
| MG4 (2022-) | MG / SAIC EV | `obdb_mg_mg4` |
| MG5/Marvel/ZS | MG / SAIC EV | `wican_mg_mg5_marvel_zs` |
| ZS EV (2019-) | MG / SAIC EV | `abrp_mgzsev` |
| ZS EV (2019-2021) | MG / SAIC EV | `obdb_mg_zs_ev` |

## Mini

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_mini` |
| Cooper SE (2020-) | Mini F56 SE | `obdb_mini_cooper_se` |
| Cooper SE (2020-2024) | Mini F56 SE | `abrp_minicooperse`, `evsoc_bmw_sme` |
| Hardtop (2001-) |  | `obdb_mini_hardtop` |
| SE Electric | Mini F56 SE | `wican_mini_cooper_se_electric` |

## Mitsubishi

| Model | Platform | Profiles |
|---|---|---|
| iMiEV/Outlander-PHEV | Mitsubishi i-MiEV family | `wican_mitsubishi_imiev_outlander_phev` |
| Outlander-PHEV 2023 | Mitsubishi Outlander PHEV | `wican_mitsubishi_outlander_phev_2023` |
| Outlander-PHEV 2025 | Mitsubishi Outlander PHEV | `wican_mitsubishi_outlander_phev_2025` |

## Nissan

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_nissan` |
| Ariya | Renault/Nissan CMF-EV / AmpR | `wican_nissan_ariya` |
| ARIYA (2022-) | Renault/Nissan CMF-EV / AmpR | `obdb_nissan_ariya` |
| e-NV200 (derived) (2014-2021) | Nissan Leaf | `evsoc_nissan_leaf_evcan` |
| Leaf (2010-) | Nissan Leaf | `obdb_nissan_leaf` |
| Leaf ZE0 / AZE0 (2011-2017) | Nissan Leaf | `evsoc_nissan_leaf_evcan` |
| leaf-ze1 | Nissan Leaf | `wican_nissan_leaf_ze1` |

## Opel

| Model | Platform | Profiles |
|---|---|---|
| Ampera-e (2017-2019) | GM Bolt / Ampera-e | `abrp_bolt17` |
| Ampere-E | GM Bolt / Ampera-e | `wican_opel_ampere_e` |
| Ampere-E 2019 | GM Bolt / Ampera-e | `wican_opel_ampere_e_2019` |
| Astra |  | `wican_opel_astra` |
| Combo-e / Vivaro-e / Zafira-e (2020-) | Stellantis e-CMP / STLA Small | `evsoc_stellantis_ecmp` |
| Corsa e (2020-) | Stellantis e-CMP / STLA Small | `obdb_vauxhallopel_corsa_e` |
| Corsa-e / Corsa Electric (2019-) | Stellantis e-CMP / STLA Small | `evsoc_stellantis_ecmp` |
| Frontera Electric (derived, experimental) (2025-) | Stellantis Smart Car | `evsoc_stellantis_smartcar` |
| Grandland X Hybrid / Hybrid4 (experimental) (2019-2024) | Stellantis EMP2 Plug-in-Hybrid | `evsoc_stellantis_phev` |
| Mokka-e / Mokka Electric (2020-) | Stellantis e-CMP / STLA Small | `evsoc_stellantis_ecmp` |

## Peugeot

| Model | Platform | Profiles |
|---|---|---|
| 208 (2012-) | Stellantis e-CMP / STLA Small | `obdb_peugeot_208` |
| 3008 Hybrid / Hybrid4 (experimental) (2019-2024) | Stellantis EMP2 Plug-in-Hybrid | `evsoc_stellantis_phev` |
| 508 Hybrid / PSE (experimental) (2019-) | Stellantis EMP2 Plug-in-Hybrid | `evsoc_stellantis_phev` |
| all models |  | `obdb_peugeot` |
| e-2008 (2019-) | Stellantis e-CMP / STLA Small | `evsoc_stellantis_ecmp` |
| e-208 | Stellantis e-CMP / STLA Small | `wican_peugeot_e_208` |
| e-208 (2019-) | Stellantis e-CMP / STLA Small | `evsoc_stellantis_ecmp` |
| e-Partner / e-Rifter / e-Expert / e-Traveller (2020-) | Stellantis e-CMP / STLA Small | `evsoc_stellantis_ecmp` |
| iON | Mitsubishi i-MiEV family | `wican_peugeot_ion` |

## Polestar

| Model | Platform | Profiles |
|---|---|---|
| 2 (2020-) | Volvo/Geely (CMA, SPA, SEA) | `obdb_polestar_2` |
| all models | Volvo/Geely (CMA, SPA, SEA) | `obdb_polestar` |
| Polestar 2 (2020-) | Volvo/Geely (CMA, SPA, SEA) | `evsoc_geely_becm` |
| Polestar 3 / 4 (derived) (2024-) | Volvo/Geely (CMA, SPA, SEA) | `evsoc_geely_becm` |

## Porsche

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_porsche` |
| Panamera (2009-) |  | `obdb_porsche_panamera` |
| Taycan | Porsche/Audi J1 | `wican_porsche_taycan` |
| Taycan (2020-) | Porsche/Audi J1 | `obdb_porsche_taycan` |

## Ram

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_ram` |

## Renault

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_renault` |
| Ariya/Scenic EV E-TECH/Renault 5 E-TECH/Renault 4 E-TECH/Megane E-TECH GSR2 2024/Master EV E-TECH | Renault/Nissan CMF-EV / AmpR | `wican_renault_ariya_scenic_ev_e_tech_renault_5_e_tech_renault_4_e_tech_megane_e_tech_gsr2_2024_master_ev_e_tech` |
| Kangoo Z.E. | Renault Zoe / Kangoo Z.E. | `wican_renault_kangoo_z_e` |
| Twizy | Renault Zoe / Kangoo Z.E. | `wican_renault_twizy` |
| ZOE (2012-2024) | Renault Zoe / Kangoo Z.E. | `obdb_renault_zoe` |
| Zoe Ph1 (2012-2019) | Renault Zoe / Kangoo Z.E. | `abrp_zoe` |
| Zoe Ph2 (2019-) | Renault Zoe / Kangoo Z.E. | `abrp_zoe2` |
| Zoe Ph2 (2020-) (2020-) | Renault Zoe / Kangoo Z.E. | `wican_renault_zoe_ph2_2020` |
| Zoe R110/R90 | Renault Zoe / Kangoo Z.E. | `wican_renault_zoe_r110_r90` |

## Rolls-Royce

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_rolls_royce` |

## Scion

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_scion` |

## Seat

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_seat` |
| Mii electric (2019-2021) | VW MEB small (e-up) | `abrp_eup` |
| Mii Electric (2019-2021) | VW MEB small (e-up) | `obdb_seat_mii_electric` |

## Skoda

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_skoda` |
| Citigo e iV (2019-2020) | VW MEB small (e-up) | `obdb_skoda_citigo_e_iv` |
| Citigo-e iV (2019-2020) | VW MEB small (e-up) | `abrp_eup` |
| Enyaq / Elroq (2020-) | VW MEB | `abrp_meb` |
| Enyaq / Enyaq Coupé / Elroq (2020-) | VW MEB | `evsoc_vw_meb` |

## smart

| Model | Platform | Profiles |
|---|---|---|
| #1 | Volvo/Geely (CMA, SPA, SEA) | `wican_smart_1` |
| #3 (derived) (2023-) | Volvo/Geely (CMA, SPA, SEA) | `evsoc_geely_becm` |
| all models |  | `obdb_smart` |
| ED (453) (2017-2019) | Renault Zoe / Kangoo Z.E. | `evsoc_smart_eq` |
| EQ |  | `wican_smart_eq` |
| EQ fortwo / forfour (453) (2017-2024) | Renault Zoe / Kangoo Z.E. | `evsoc_smart_eq` |
| fortwo (1998-2024) |  | `obdb_smart_fortwo` |
| fortwo electric drive (451, experimental) (2012-2016) | smart electric drive (451) | `evsoc_smart_ed451` |

## Subaru

| Model | Platform | Profiles |
|---|---|---|
| Solterra (2022-) | Toyota/Subaru e-TNGA | `evsoc_toyota_etnga` |

## Suzuki

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_suzuki` |

## Tata

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_tata` |

## Tesla

| Model | Platform | Profiles |
|---|---|---|
| Model 3 (2017-) | Tesla Model 3/Y | `evsoc_tesla_model3y` |
| Model S (2012-2020) | Tesla Model S/X | `evsoc_tesla_models` |
| Model X (2015-2020) | Tesla Model S/X | `evsoc_tesla_models` |
| Model Y (2020-) | Tesla Model 3/Y | `evsoc_tesla_model3y` |

## Toyota

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_toyota` |
| bZ4X (2022-) | Toyota/Subaru e-TNGA | `evsoc_toyota_etnga`, `obdb_toyota_bz4x` |
| bZ4X 2022-2025 | Toyota/Subaru e-TNGA | `wican_toyota_bz4x_2022_2025` |
| C HR (2016-) |  | `obdb_toyota_c_hr` |
| Camry Hybrid (2007-) |  | `obdb_toyota_camry_hybrid` |
| Corolla (1966-) |  | `obdb_toyota_corolla` |
| Corolla Cross (2020-) |  | `obdb_toyota_corolla_cross` |
| Corolla Hybrid (2019-) |  | `obdb_toyota_corolla_hybrid` |
| Grand Highlander (2023-) |  | `obdb_toyota_grand_highlander` |
| Grand Highlander Hybrid (2023-) |  | `obdb_toyota_grand_highlander_hybrid` |
| Highlander (2001-) |  | `obdb_toyota_highlander` |
| Land Cruiser (1960-) |  | `obdb_toyota_land_cruiser` |
| Land Cruiser Hybrid (2015-) |  | `obdb_toyota_land_cruiser_hybrid` |
| Prius (1997-) |  | `obdb_toyota_prius` |
| Prius Prime (2012-) |  | `obdb_toyota_prius_prime` |
| Proace (City) Electric (2020-) | Stellantis e-CMP / STLA Small | `evsoc_stellantis_ecmp` |
| Rav4 |  | `wican_toyota_rav4` |
| RAV4 Hybrid (2016-) |  | `obdb_toyota_rav4_hybrid` |
| RAV4 Prime (2020-) |  | `obdb_toyota_rav4_prime` |
| Sequoia (2000-) |  | `obdb_toyota_sequoia` |
| Sienna (1998-) |  | `obdb_toyota_sienna` |
| Sienna Hybrid (2021-) |  | `obdb_toyota_sienna_hybrid` |
| Tundra (1999-) |  | `obdb_toyota_tundra` |
| Venza (2009-) |  | `obdb_toyota_venza` |
| Venza Hybrid (2021-) |  | `obdb_toyota_venza_hybrid` |
| Yaris (1998-) |  | `obdb_toyota_yaris` |
| Yaris Cross (2020-) |  | `obdb_toyota_yaris_cross` |

## Vauxhall

| Model | Platform | Profiles |
|---|---|---|
| Corsa e (2020-) | Stellantis e-CMP / STLA Small | `obdb_vauxhallopel_corsa_e` |
| Corsa-e / Mokka-e (2019-) | Stellantis e-CMP / STLA Small | `evsoc_stellantis_ecmp` |
| Grandland X Hybrid (experimental) (2019-2024) | Stellantis EMP2 Plug-in-Hybrid | `evsoc_stellantis_phev` |

## Volkswagen

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_volkswagen` |
| e Golf (2014-2020) | VW e-Golf | `obdb_volkswagen_e_golf` |
| e Up (2013-2023) | VW MEB small (e-up) | `obdb_volkswagen_e_up` |
| e-Golf | VW e-Golf | `wican_vw_e_golf` |
| e-Golf (2014-2020) | VW e-Golf | `abrp_egolf` |
| e-Up | VW MEB small (e-up) | `wican_vw_e_up` |
| e-up! (2013-) | VW MEB small (e-up) | `abrp_eup` |
| EV MEB: ID.3, ID.4, ID.5, ID.6, ID.7, ID.Buzz, Enyaq, Elroq, Q4 E-tron, Q6 e-tron, Cupra Born, Cupra Tavascan, Porsche Macan EV, Ford Explorer EV, Capri EV | VW MEB | `wican_audi_ev_meb_id_3_id_4_id_5_id_6_id_7_id_buzz_enyaq_elroq_q4_e_tron_q6_e_tron_cupra_born_cupra_tavascan_porsche_macan_ev_ford_explorer_ev_capri_ev` |
| ID | VW MEB | `wican_vw_id` |
| ID.3 / ID.4 / ID.5 / ID.7 / ID.Buzz (2020-) | VW MEB | `abrp_meb`, `evsoc_vw_meb` |
| ID.4 (2020-) | VW MEB | `obdb_volkswagen_id_4` |
| Passat (1973-) |  | `obdb_volkswagen_passat` |

## Volvo

| Model | Platform | Profiles |
|---|---|---|
| all models |  | `obdb_volvo` |
| EX30 / EC40 / EX40 / C40 / XC40 Recharge (2020-) | Volvo/Geely (CMA, SPA, SEA) | `evsoc_geely_becm` |
| EX90 / ES90 (derived) (2024-) | Volvo/Geely (CMA, SPA, SEA) | `evsoc_geely_becm` |
| S60 (2000-2024) | Volvo/Geely (CMA, SPA, SEA) | `obdb_volvo_s60` |
| XC40 | Volvo/Geely (CMA, SPA, SEA) | `wican_volvo_xc40` |
| XC40 (2017-) | Volvo/Geely (CMA, SPA, SEA) | `obdb_volvo_xc40` |
| XC40 BEV | Volvo/Geely (CMA, SPA, SEA) | `wican_volvo_xc40_bev` |
| XC60 (2008-) | Volvo/Geely (CMA, SPA, SEA) | `obdb_volvo_xc60` |
| XC60 / XC90 / S60 / V60 / S90 / V90 Recharge (PHEV) (2016-) | Volvo/Geely (CMA, SPA, SEA) | `evsoc_geely_becm` |
| XC60 PHEV | Volvo/Geely (CMA, SPA, SEA) | `wican_volvo_xc60_phev` |
| XC90 (2002-) | Volvo/Geely (CMA, SPA, SEA) | `obdb_volvo_xc90` |

## Xpeng

| Model | Platform | Profiles |
|---|---|---|
| P5/P7/G6/G9/X9 |  | `wican_xpeng_p5_p7_g6_g9_x9` |

## Zeekr

| Model | Platform | Profiles |
|---|---|---|
| 001 | Volvo/Geely (CMA, SPA, SEA) | `wican_zeekr_001` |
| 001 / 7X / X (7X/X derived) (2021-) | Volvo/Geely (CMA, SPA, SEA) | `evsoc_geely_becm` |

