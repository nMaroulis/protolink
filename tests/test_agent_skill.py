"""Tests for the AgentSkill class."""

from protolink.core.agent_card import AgentSkill


class TestAgentSkill:
    """Test cases for the AgentSkill class."""

    def test_agent_skill_initialization_minimal(self):
        """Test AgentSkill initialization with only required fields."""
        skill = AgentSkill(id="test-skill")

        assert skill.id == "test-skill"
        assert skill.description == ""
        assert skill.tags == []
        assert skill.examples == []

    def test_agent_skill_initialization_full(self):
        """Test AgentSkill initialization with all fields."""
        skill = AgentSkill(
            id="full-skill",
            description="A comprehensive skill for testing",
            tags=["test", "example", "skill"],
            examples=["Example 1", "Example 2"],
        )

        assert skill.id == "full-skill"
        assert skill.description == "A comprehensive skill for testing"
        assert skill.tags == ["test", "example", "skill"]
        assert skill.examples == ["Example 1", "Example 2"]

    def test_agent_skill_with_none_values(self):
        """Test AgentSkill initialization with None values for optional fields."""
        skill = AgentSkill(id="none-skill", description=None, tags=None, examples=None)

        assert skill.id == "none-skill"
        assert skill.description is None  # description stays None
        assert skill.tags == []  # tags gets converted to empty list
        assert skill.examples == []  # examples gets converted to empty list

    def test_agent_skill_post_init_validation(self):
        """Test that __post_init__ properly handles None values."""
        skill = AgentSkill(id="validation-skill")

        # Manually set to None to test post_init
        skill.tags = None
        skill.examples = None
        skill.__post_init__()

        assert skill.tags == []
        assert skill.examples == []

    def test_agent_skill_equality(self):
        """Test AgentSkill equality comparison."""
        skill1 = AgentSkill(id="same-skill", description="Same description")
        skill2 = AgentSkill(id="same-skill", description="Same description")
        skill3 = AgentSkill(id="different-skill", description="Same description")

        # Note: dataclass implements equality based on all fields
        assert skill1 == skill2
        assert skill1 != skill3

    def test_agent_skill_repr(self):
        """Test AgentSkill string representation."""
        skill = AgentSkill(id="repr-skill", description="Skill for repr testing")
        repr_str = repr(skill)

        assert "repr-skill" in repr_str
        assert "Skill for repr testing" in repr_str

    def test_agent_skill_mutable_fields(self):
        """Test that AgentSkill fields are mutable."""
        skill = AgentSkill(id="mutable-skill")

        # Modify fields
        skill.description = "Updated description"
        skill.tags.append("new-tag")
        skill.examples.append("New example")

        assert skill.description == "Updated description"
        assert "new-tag" in skill.tags
        assert "New example" in skill.examples

    def test_agent_skill_with_empty_collections(self):
        """Test AgentSkill with empty collections."""
        skill = AgentSkill(id="empty-collections", description="Skill with empty collections", tags=[], examples=[])

        assert skill.tags == []
        assert skill.examples == []
        assert len(skill.tags) == 0
        assert len(skill.examples) == 0

    def test_agent_skill_id_validation(self):
        """Test AgentSkill with various ID formats."""
        valid_ids = ["simple-skill", "skill_with_underscores", "skill.with.dots", "skill123", "SKILL-WITH-CAPS"]

        for skill_id in valid_ids:
            skill = AgentSkill(id=skill_id)
            assert skill.id == skill_id

    def test_agent_skill_description_types(self):
        """Test AgentSkill with different description types."""
        descriptions = [
            "Simple description",
            "Multi-line\ndescription\nwith\nnewlines",
            "Description with special chars: !@#$%^&*()",
            "",  # Empty description
            "   ",  # Whitespace-only description
        ]

        for desc in descriptions:
            skill = AgentSkill(id="desc-test", description=desc)
            assert skill.description == desc

    def test_agent_skill_tag_operations(self):
        """Test various tag operations on AgentSkill."""
        skill = AgentSkill(id="tag-test")

        # Add tags
        skill.tags.extend(["tag1", "tag2", "tag3"])
        assert len(skill.tags) == 3

        # Remove tag
        skill.tags.remove("tag2")
        assert "tag2" not in skill.tags
        assert len(skill.tags) == 2
        # Clear tags
        skill.tags.clear()
        assert len(skill.tags) == 0

    def test_agent_skill_example_operations(self):
        """Test various example operations on AgentSkill."""
        skill = AgentSkill(id="example-test")

        # Add examples
        skill.examples.extend(["Example 1", "Example 2", "Example 3"])
        assert len(skill.examples) == 3

        # Replace example
        skill.examples[1] = "Updated Example 2"
        assert skill.examples[1] == "Updated Example 2"
        # Clear examples
        skill.examples.clear()
        assert len(skill.examples) == 0
