#include <google/protobuf/compiler/importer.h>
#include <google/protobuf/descriptor.h>
#include <google/protobuf/descriptor_database.h>
#include <google/protobuf/dynamic_message.h>
#include <google/protobuf/message.h>
#include <google/protobuf/timestamp.pb.h>
#include <google/protobuf/util/json_util.h>
#include <google/protobuf/wrappers.pb.h>
#include <nlohmann/json.hpp>

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>

namespace
{
const std::unordered_map<std::string, std::string> kMessageTypes{
    {"BattleConfig", "Digit.PrimeServer.Models.StaticSyncBattleConfResponse"},
    {"ThreatConfig", "Digit.PrimeServer.Models.StaticSyncThreatConfResponse"},
    {"ClientShipStatLookupSpecs", "Digit.PrimeServer.Models.ClientShipStatLookupSpecsResponse"},
    {"BaseShipTierSpecs", "Digit.PrimeServer.Models.StaticSyncBaseShipTierSpecsResponse"},
    {"ShipTierSpecs", "Digit.PrimeServer.Models.StaticSyncShipTierSpecsResponse"},
    {"MitigationCapsSpecs", "Digit.PrimeServer.Models.StaticSyncMitigationCapsSpecResponse"},
    {"GlobalDamageReductionConfig", "Digit.PrimeServer.Models.StaticSyncGlobalDamageReductionConfigResponse"},
    {"HullSpecs", "Digit.PrimeServer.Models.StaticSyncHullSpecsResponse"},
    {"ComponentSpecs", "Digit.PrimeServer.Models.ComponentSpecResponse"},
    {"OfficerSpecs", "Digit.PrimeServer.Models.StaticSyncOfficerSpecsResponse"},
    {"Officers", "Digit.PrimeServer.Models.OfficersResponse"},
    {"OfficerAbilityBuffSpecs", "Digit.PrimeServer.Models.StaticSyncOfficerAbilitySpecsResponse"},
    {"OfficerCoreStatSpecs", "Digit.PrimeServer.Models.StaticSyncOfficerCoreStatSpecsResponse"},
    {"OfficerCoreStatThresholdsSpecs", "Digit.PrimeServer.Models.StaticSyncOfficerCoreStatThresholdsSpecsResponse"},
    {"OfficerSynergyFactorSpecs", "Digit.PrimeServer.Models.StaticSyncOfficerSynergyFactorSpecsResponse"},
    {"ShipBonusBuffSpecs", "Digit.PrimeServer.Models.StaticSyncShipBonusSpecsResponse"},
    {"BuffTargetSpecs", "Digit.PrimeServer.Models.StaticSyncBuffTargetSpecsResponse"},
    {"BuffTriggerSpecs", "Digit.PrimeServer.Models.StaticSyncBuffTriggerSpecsResponse"},
    {"ActionSpecs", "Digit.PrimeServer.Models.StaticSyncActionSpecResponse"},
    {"ShipLevelUpBonusBuffsSpecs", "Digit.PrimeServer.Models.StaticSyncShipLevelUpBonusBuffSpecResponse"},
    {"ResearchSpecs", "Digit.PrimeServer.Models.StaticSyncResearchTreeSpecsResponse"},
    {"ResearchTreesState", "Digit.PrimeServer.Models.ResearchTreesState"},
    {"StarbaseBuffs", "Digit.PrimeServer.Models.StaticSyncStarbaseBuffsSpecsResponse"},
    {"GlobalActiveBuffs", "Digit.PrimeServer.Models.GlobalActiveBuffsResponse"},
    {"ConsumableSpecs", "Digit.PrimeServer.Models.StaticSyncConsumableSpecsResponse"},
    {"ConsumableBuffs", "Digit.PrimeServer.Models.StaticSyncConsumableBuffsSpecsResponse"},
    {"SlotSpecs", "Digit.PrimeServer.Models.StaticSyncSlotSpecsResponse"},
    {"EntitySlots", "Digit.PrimeServer.Models.EntitySlots"},
    {"EntitySlotsData", "Digit.PrimeServer.Models.EntitySlotsData"},
    {"ActiveOfficerTraits", "Digit.PrimeServer.Models.OfficerTraitsResponse"},
    {"CommanderSkillSpecs", "Digit.PrimeServer.Models.StaticSyncCommanderSkillSpecsResponse"},
    {"ForbiddenTechSpecs", "Digit.PrimeServer.Models.StaticSyncForbiddenTechSpecsResponse"},
    {"ForbiddenTechs", "Digit.PrimeServer.Models.ForbiddenTechsResponse"},
    {"ForbiddenTechBuffs", "Digit.PrimeServer.Models.StaticSyncForbiddenTechBuffsSpecsResponse"},
    {"ActivatedAbilitySpecs", "Digit.PrimeServer.Models.StaticSyncActivatedAbilitySpecsResponse"},
    {"ActivatedShipAbilitiesConfigs", "Digit.PrimeServer.Models.StaticSyncActivatedShipAbilityConfigsResponse"},
    {"LocalizationCacheData", "Digit.Client.Localization.LocalizationCacheData"},
};

class ProtoErrorCollector final : public google::protobuf::compiler::MultiFileErrorCollector
{
public:
  void RecordError(absl::string_view filename, int line, int column, absl::string_view message) override
  { std::cerr << filename << ":" << line + 1 << ":" << column + 1 << ": " << message << '\n'; }
};

class ProtoSchema
{
public:
  explicit ProtoSchema(const std::filesystem::path& proto_root)
      : generated_database_(*google::protobuf::DescriptorPool::generated_pool())
      , source_database_(&source_tree_, &generated_database_)
      , pool_(&source_database_, source_database_.GetValidationErrorCollector())
      , factory_(&pool_)
  {
    google::protobuf::Timestamp::descriptor();
    google::protobuf::Int64Value::descriptor();
    source_tree_.MapPath("", proto_root.string());
    source_database_.RecordErrorsTo(&errors_);

    if (pool_.FindFileByName("Digit.PrimeServer.Models.proto") == nullptr) {
      throw std::runtime_error("failed to load Digit.PrimeServer.Models.proto from " + proto_root.string());
    }
    if (pool_.FindFileByName("Digit.Client.Localization.proto") == nullptr) {
      throw std::runtime_error("failed to load Digit.Client.Localization.proto from " + proto_root.string());
    }
  }

  std::unique_ptr<google::protobuf::Message> NewMessage(const std::string& group, const std::string& type_name)
  {
    const auto* descriptor = pool_.FindMessageTypeByName(type_name);
    if (descriptor == nullptr) {
      throw std::runtime_error("missing protobuf descriptor for entity group " + group + ": " + type_name);
    }

    const auto* prototype = factory_.GetPrototype(descriptor);
    if (prototype == nullptr) {
      throw std::runtime_error("missing protobuf prototype for entity group " + group + ": " + type_name);
    }

    return std::unique_ptr<google::protobuf::Message>(prototype->New());
  }

private:
  google::protobuf::compiler::DiskSourceTree               source_tree_;
  ProtoErrorCollector                                      errors_;
  google::protobuf::DescriptorPoolDatabase                 generated_database_;
  google::protobuf::compiler::SourceTreeDescriptorDatabase source_database_;
  google::protobuf::DescriptorPool                         pool_;
  google::protobuf::DynamicMessageFactory                  factory_;
};

std::filesystem::path FindProtoRoot()
{
  if (const char* env = std::getenv("STFC_PROTO_ROOT"); env != nullptr && *env != '\0') {
    return env;
  }

  for (auto dir = std::filesystem::current_path(); !dir.empty(); dir = dir.parent_path()) {
    const auto candidate = dir / "mods" / "src" / "prime" / "proto";
    if (std::filesystem::exists(candidate / "Digit.PrimeServer.Models.proto")) {
      return candidate;
    }

    if (dir == dir.root_path()) {
      break;
    }
  }

  throw std::runtime_error("could not find mods/src/prime/proto; run from the repo or set STFC_PROTO_ROOT");
}

std::string ReadFile(const std::filesystem::path& path)
{
  std::ifstream in(path, std::ios::binary);
  if (!in.is_open()) {
    throw std::runtime_error("failed to open " + path.string());
  }
  return {std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};
}

void DecodeOne(ProtoSchema& schema, const std::filesystem::path& capture_root, const nlohmann::json& manifest_entry,
               const std::filesystem::path& out_dir)
{
  const auto group = manifest_entry.at("entity_group").get<std::string>();
  const auto it    = kMessageTypes.find(group);
  if (it == kMessageTypes.end()) {
    throw std::runtime_error("unsupported entity group: " + group);
  }

  auto       message = schema.NewMessage(group, it->second);
  const auto bytes   = ReadFile(capture_root / manifest_entry.at("path").get<std::string>());
  if (!message->ParseFromString(bytes)) {
    throw std::runtime_error("failed to parse entity group: " + group);
  }

  std::string                              json;
  google::protobuf::util::JsonPrintOptions options;
  options.add_whitespace             = true;
  options.preserve_proto_field_names = true;
  const auto status                  = google::protobuf::util::MessageToJsonString(*message, &json, options);
  if (!status.ok()) {
    throw std::runtime_error("failed to convert entity group to JSON: " + group);
  }

  std::filesystem::create_directories(out_dir);
  std::ofstream out(out_dir / (group + ".json"));
  out << json << '\n';
}
} // namespace

int main(int argc, char** argv)
{
  try {
    if (argc != 3) {
      std::cerr << "usage: combat-model-fixture <capture-root> <out-dir>\n";
      return 2;
    }

    const std::filesystem::path capture_root = argv[1];
    const std::filesystem::path out_dir      = argv[2];
    std::ifstream               manifest(capture_root / "manifest.jsonl");
    if (!manifest.is_open()) {
      std::cerr << "missing manifest.jsonl under " << capture_root << "\n";
      return 2;
    }

    ProtoSchema schema(FindProtoRoot());

    std::string line;
    while (std::getline(manifest, line)) {
      if (line.empty()) {
        continue;
      }
      const auto entry = nlohmann::json::parse(line);
      if (entry.value("kind", "") == "entity_group") {
        DecodeOne(schema, capture_root, entry, out_dir);
      }
    }
  } catch (const std::exception& e) {
    std::cerr << "combat-model-fixture: " << e.what() << '\n';
    return 1;
  }

  return 0;
}
