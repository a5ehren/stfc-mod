from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_H = PROJECT_ROOT / "mods" / "src" / "config.h"
CONFIG_CC = PROJECT_ROOT / "mods" / "src" / "config.cc"
DEFAULTCONFIG_H = PROJECT_ROOT / "mods" / "src" / "defaultconfig.h"
EXAMPLE_TOML = PROJECT_ROOT / "example_community_patch_settings.toml"
SYNC_CC = PROJECT_ROOT / "mods" / "src" / "patches" / "parts" / "sync.cc"
DECODER_CC = PROJECT_ROOT / "tools" / "combat-model" / "src" / "main.cc"


class CombatModelCaptureStaticTests(unittest.TestCase):
    def test_capture_config_defaults_disabled(self) -> None:
        config_h = CONFIG_H.read_text(encoding="utf-8-sig")
        config_cc = CONFIG_CC.read_text(encoding="utf-8-sig")
        defaults = DEFAULTCONFIG_H.read_text(encoding="utf-8-sig")
        example = EXAMPLE_TOML.read_text(encoding="utf-8-sig")

        self.assertIn("combat_model_capture_enabled;", config_h)
        self.assertIn("std::string combat_model_capture_dir;", config_h)
        self.assertIn("combat_model_capture_enabled", config_cc)
        self.assertIn('get_config_or_default(config, parsed, "combat_model", "capture_enabled"', config_cc)
        self.assertNotIn("combat_model_capture_threat_ratings", config_h)
        self.assertNotIn("combat_model_capture_threat_ratings", config_cc)
        self.assertNotIn("combat_model_capture_hooks_enabled", config_h)
        self.assertNotIn("combat_model_capture_hooks_enabled", config_cc)
        self.assertNotIn('get_config_or_default(config, parsed, "combat_model", "threat_ratings"', config_cc)
        self.assertNotIn("combat_model_capture_localization_trace", config_h)
        self.assertNotIn("combat_model_capture_localization_trace", config_cc)
        self.assertNotIn('get_config_or_default(config, parsed, "combat_model", "localization_trace"', config_cc)
        self.assertIn("constexpr bool        capture_enabled", defaults)
        self.assertNotIn("constexpr bool        threat_ratings", defaults)
        self.assertNotIn("constexpr bool        localization_trace", defaults)
        self.assertIn("capture_enabled = false", example)
        self.assertNotIn("threat_ratings = false", example)
        self.assertNotIn("localization_trace = false", example)

    def test_capture_helper_names_required_static_groups(self) -> None:
        header = (PROJECT_ROOT / "mods" / "src" / "patches" / "parts" / "combat_model_capture.h").read_text(
            encoding="utf-8-sig"
        )
        source = (PROJECT_ROOT / "mods" / "src" / "patches" / "parts" / "combat_model_capture.cc").read_text(
            encoding="utf-8-sig"
        )

        self.assertIn("CaptureEntityGroup", header)
        self.assertIn("CaptureBattleJournal", header)
        self.assertNotIn("CaptureLocalizationCacheData", header)
        for group in (
            "BattleConfig",
            "ThreatConfig",
            "ClientShipStatLookupSpecs",
            "BaseShipTierSpecs",
            "ShipTierSpecs",
            "MitigationCapsSpecs",
            "GlobalDamageReductionConfig",
            "HullSpecs",
            "ComponentSpecs",
            "OfficerSpecs",
            "Officers",
            "OfficerAbilityBuffSpecs",
            "OfficerCoreStatSpecs",
            "OfficerCoreStatThresholdsSpecs",
            "OfficerSynergyFactorSpecs",
            "BuffTargetSpecs",
            "BuffTriggerSpecs",
            "ActionSpecs",
            "ForbiddenTechSpecs",
            "ShipBonusBuffSpecs",
            "ShipLevelUpBonusBuffsSpecs",
            "ResearchSpecs",
            "ResearchTreesState",
            "StarbaseBuffs",
            "GlobalActiveBuffs",
            "ConsumableSpecs",
            "ConsumableBuffs",
            "SlotSpecs",
            "EntitySlots",
            "EntitySlotsData",
            "ActiveOfficerTraits",
            "CommanderSkillSpecs",
            "ForbiddenTechs",
        ):
            with self.subTest(group=group):
                self.assertIn(group, source)

    def test_localization_cache_capture_hooks_removed_from_mod(self) -> None:
        source = (PROJECT_ROOT / "mods" / "src" / "patches" / "parts" / "combat_model_capture.cc").read_text(
            encoding="utf-8-sig"
        )

        self.assertNotIn("CaptureLocalizationCacheData", source)
        self.assertNotIn('"entity_group", "LocalizationCacheData"', source)
        self.assertNotIn('"source", "client_localization_cache"', source)
        self.assertNotIn('NextStem("LocalizationCacheData")', source)

    def test_localization_trace_hooks_removed_from_mod(self) -> None:
        source = (PROJECT_ROOT / "mods" / "src" / "patches" / "parts" / "combat_model_capture.cc").read_text(
            encoding="utf-8-sig"
        )
        patches = (PROJECT_ROOT / "mods" / "src" / "patches" / "patches.cc").read_text(encoding="utf-8-sig")

        self.assertNotIn("CaptureLocalizationTraceEvent", source)
        self.assertNotIn("LocalizationTraceEnabled", source)
        self.assertNotIn("localization_trace.jsonl", source)
        self.assertNotIn("combat_model_capture_hooks_enabled", patches)

        removed_hooks = (
            "LocalizationCacheDatabase_AddTranslationsInner",
            "LocalizationCacheDatabase_set_SelectedLanguageCode",
            "LanguageManager_set_LocaleDB",
            "LanguageManager_set_SelectedLanguage",
            "LanguageManager_TryGetTranslation",
            "SettingsSectionDirector_SetLanguage",
            "SettingsSectionDirector_OnLanguageLoaded",
            "TranslationService_RequestStaticCategory",
            "TranslationService_RequestDynamicCategorySingleLong",
            "TranslationService_RequestDynamicCategorySingleString",
            "TranslationService_RequestDynamicCategoryMultiLong",
            "TranslationService_RequestDynamicCategoryMultiString",
            "RequestDispatcher_GetDefaultGetRequest",
            "TranslationDataContainer_ParseBinaryObject",
        )
        for hook in removed_hooks:
            with self.subTest(hook=hook):
                self.assertNotIn(hook, source)
        self.assertNotIn("INSTALL_LOCALIZATION_HOOK", source)
        self.assertNotIn("INSTALL_LOCALIZATION_METHOD_INFO", source)
        self.assertNotIn("TranslationDataContainer_HandleResponseData", source)

    def test_threat_rating_hooks_removed_from_mod(self) -> None:
        source = (PROJECT_ROOT / "mods" / "src" / "patches" / "parts" / "combat_model_capture.cc").read_text(
            encoding="utf-8-sig"
        )
        patches = (PROJECT_ROOT / "mods" / "src" / "patches" / "patches.cc").read_text(encoding="utf-8-sig")

        self.assertNotIn("CombatModelCaptureHooks", patches)
        self.assertNotIn("InstallCombatModelCaptureHooks", patches)
        self.assertNotIn("InstallCombatModelCaptureHooks", source)
        self.assertNotIn("CaptureThreatLevelEvent", source)
        self.assertNotIn("threat_level.jsonl", source)

        removed_hooks = (
            "ThreatLevelService_CalculateFleetWeaponRating",
            "ThreatLevelService_CalculateFleetRating",
            "ThreatLevelService_CalculateFleetTotalStrengthRating",
            "SpecService_GetPlatingRatingParam",
            "SpecService_GetDodgeRatingParam",
            "SpecService_GetAbsorptionRatingParam",
            "SpecService_GetMinDamageRatingParam",
            "SpecService_GetMaxDamageRatingParam",
            "SpecService_GetAccuracyRatingParam",
            "SpecService_GetPenetrationRatingParam",
            "SpecService_GetModulationRatingParam",
            "SpecService_GetAverageDamageRatingParam",
            "SpecService_GetNumberOfShotsRatingParam",
            "SpecService_GetReloadTimeRatingParam",
            "SpecService_GetCriticalChanceRatingParam",
            "SpecService_GetCriticalDamageRatingParam",
            "SpecService_GetDPRRatingParam",
            "SpecService_GetAttackRatingParam",
            "SpecService_GetDefenseRatingParam",
            "SpecService_GetHealthRatingParam",
            "SpecService_GetCoreStatOneRatingParam",
            "SpecService_GetCoreStatTwoRatingParam",
            "SpecService_GetCoreStatThreeRatingParam",
            "SpecService_GetOfficerRatingFactorRatingParam",
            "SpecService_GetIsolyticDamageRatingParam",
            "SpecService_GetForbiddenTechRatingParam",
        )
        for hook in removed_hooks:
            with self.subTest(hook=hook):
                self.assertNotIn(hook, source)
        self.assertNotIn("INSTALL_THREAT_LEVEL_HOOK", source)
        self.assertNotIn("INSTALL_SPEC_RATING_PARAM_HOOK", source)

    def test_decoder_maps_player_buff_groups_to_expected_protobuf_messages(self) -> None:
        decoder = DECODER_CC.read_text(encoding="utf-8-sig")

        expected_mappings = {
            "ShipBonusBuffSpecs": "Digit.PrimeServer.Models.StaticSyncShipBonusSpecsResponse",
            "ThreatConfig": "Digit.PrimeServer.Models.StaticSyncThreatConfResponse",
            "BaseShipTierSpecs": "Digit.PrimeServer.Models.StaticSyncBaseShipTierSpecsResponse",
            "ShipTierSpecs": "Digit.PrimeServer.Models.StaticSyncShipTierSpecsResponse",
            "OfficerCoreStatSpecs": "Digit.PrimeServer.Models.StaticSyncOfficerCoreStatSpecsResponse",
            "OfficerCoreStatThresholdsSpecs": (
                "Digit.PrimeServer.Models.StaticSyncOfficerCoreStatThresholdsSpecsResponse"
            ),
            "ShipLevelUpBonusBuffsSpecs": "Digit.PrimeServer.Models.StaticSyncShipLevelUpBonusBuffSpecResponse",
            "ResearchSpecs": "Digit.PrimeServer.Models.StaticSyncResearchTreeSpecsResponse",
            "ResearchTreesState": "Digit.PrimeServer.Models.ResearchTreesState",
            "StarbaseBuffs": "Digit.PrimeServer.Models.StaticSyncStarbaseBuffsSpecsResponse",
            "GlobalActiveBuffs": "Digit.PrimeServer.Models.GlobalActiveBuffsResponse",
            "ConsumableSpecs": "Digit.PrimeServer.Models.StaticSyncConsumableSpecsResponse",
            "ConsumableBuffs": "Digit.PrimeServer.Models.StaticSyncConsumableBuffsSpecsResponse",
            "SlotSpecs": "Digit.PrimeServer.Models.StaticSyncSlotSpecsResponse",
            "EntitySlots": "Digit.PrimeServer.Models.EntitySlots",
            "EntitySlotsData": "Digit.PrimeServer.Models.EntitySlotsData",
            "Officers": "Digit.PrimeServer.Models.OfficersResponse",
            "ActiveOfficerTraits": "Digit.PrimeServer.Models.OfficerTraitsResponse",
            "CommanderSkillSpecs": "Digit.PrimeServer.Models.StaticSyncCommanderSkillSpecsResponse",
            "ForbiddenTechs": "Digit.PrimeServer.Models.ForbiddenTechsResponse",
            "LocalizationCacheData": "Digit.Client.Localization.LocalizationCacheData",
        }

        for group, type_name in expected_mappings.items():
            with self.subTest(group=group):
                self.assertIn(f'{{"{group}", "{type_name}"}}', decoder)
        self.assertIn("missing protobuf descriptor for entity group", decoder)

    def test_sync_calls_capture_helper(self) -> None:
        sync_cc = SYNC_CC.read_text(encoding="utf-8-sig")

        self.assertIn('#include "combat_model_capture.h"', sync_cc)
        self.assertIn("combat_model_capture::CaptureEntityGroup", sync_cc)
        self.assertIn("combat_model_capture::CaptureBattleJournal", sync_cc)


if __name__ == "__main__":
    unittest.main()
