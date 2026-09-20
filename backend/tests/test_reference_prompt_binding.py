from app import media


def test_reference_name_map_links_character_marker_to_style_image():
    refs = [
        {"name": "岚牙造型", "kind": "character_style", "url": "https://example/lan.jpg"},
        {"name": "洛汐造型", "kind": "character_style", "url": "https://example/luo.jpg"},
    ]

    mapping = media._ref_name_map(refs)

    assert mapping["岚牙"] == 1
    assert mapping["洛汐"] == 2
    assert media._resolve_ref_markers(
        "「洛汐」面部与服饰造型以 @设定图[洛汐] 为准", mapping
    ) == "「洛汐」面部与服饰造型以 @图片2 为准"


def test_ark_content_uses_same_number_in_prompt_and_attachment_order():
    content = media._build_ark_content(
        "洛汐造型与外貌以 @设定图[洛汐] 为准",
        "seedance-2-0-pro",
        reference_images=[
            {"name": "岚牙造型", "kind": "character_style", "url": "https://example/lan.jpg"},
            {"name": "洛汐造型", "kind": "character_style", "url": "https://example/luo.jpg"},
        ],
    )

    assert "洛汐造型与外貌以 @图片2 为准" in content[0]["text"]
    assert content[2]["image_url"]["url"] == "https://example/luo.jpg"
