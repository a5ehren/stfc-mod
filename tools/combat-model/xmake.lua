target("combat-model-fixture")
do
    set_kind("binary")
    add_files("src/*.cc")
    add_packages("protobuf", "nlohmann_json")
    add_links("protoc")
end
