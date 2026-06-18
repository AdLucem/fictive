from fictive.parse_scenario_config import load_scenario_config

if __name__ == "__main__":
    scenario_dir = "sample_scenarios/forest_monster_scenario"   
    model = "test-model"

    schema, agent_configs, author_intent = load_scenario_config(
        scenario_dir
    )

    print("Schema:", schema)
    print("Agents:", agent_configs)
    print("Author Intent:", author_intent)
