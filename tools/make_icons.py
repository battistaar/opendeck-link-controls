"""Draw the plugin's key icons. Needs Pillow; run from the repository root."""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path("io.github.battistaar.linkcontrols.sdPlugin/icons")
GREY = (224, 224, 224, 255)
ORANGE = (247, 130, 27, 255)
SIZE = 288  # drawn at 2x, saved at both sizes


def canvas():
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image)


def save(image, name):
    image.save(OUT / f"{name}@2x.png")
    image.resize((SIZE // 2, SIZE // 2), Image.LANCZOS).save(OUT / f"{name}.png")


def arrow(angle):
    image, draw = canvas()
    draw.line([(144, 216), (144, 76)], fill=GREY, width=22)
    draw.line([(80, 140), (144, 76), (208, 140)], fill=GREY, width=22, joint="curve")
    return image.rotate(angle, resample=Image.BICUBIC)


def magnifier(plus):
    image, draw = canvas()
    draw.ellipse([56, 48, 196, 188], outline=GREY, width=20)
    draw.line([(178, 172), (236, 234)], fill=GREY, width=26)
    draw.line([(92, 118), (160, 118)], fill=GREY, width=18)
    if plus:
        draw.line([(126, 84), (126, 152)], fill=GREY, width=18)
    return image


def tracking(colour):
    image, draw = canvas()
    x0, y0, x1, y1, length = 50, 40, 238, 220, 50
    for x, y, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        draw.line([(x, y), (x + dx * length, y)], fill=colour, width=18)
        draw.line([(x, y), (x, y + dy * length)], fill=colour, width=18)
    draw.ellipse([110, 72, 178, 140], outline=colour, width=16)
    draw.arc([86, 150, 202, 266], 200, 340, fill=colour, width=16)
    return image


def preset():
    # A bookmark, with room below for the preset number as the key title.
    image, draw = canvas()
    draw.line([(96, 40), (192, 40), (192, 190), (144, 150), (96, 190), (96, 40)],
              fill=GREY, width=18, joint="curve")
    return image


def camera():
    image, draw = canvas()
    draw.rounded_rectangle([60, 60, 228, 228], radius=40, outline=GREY, width=18)
    draw.ellipse([104, 104, 184, 184], outline=GREY, width=18)
    return image


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, angle in (("up", 0), ("left", 90), ("down", 180), ("right", 270)):
        save(arrow(angle), f"pan-{name}")
    save(magnifier(True), "zoom-in")
    save(magnifier(False), "zoom-out")
    save(tracking(GREY), "tracking-off")
    save(tracking(ORANGE), "tracking-on")
    save(preset(), "preset")
    save(camera(), "plugin")
    save(camera(), "category")


if __name__ == "__main__":
    main()
