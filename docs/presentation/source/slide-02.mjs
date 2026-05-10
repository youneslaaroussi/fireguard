export async function slide02(presentation, ctx) {
  const slide = presentation.slides.add();
  await ctx.addImage(slide, {
    path: new URL("../slides/slide-02-coordination-gap.png", import.meta.url).pathname,
    x: 0,
    y: 0,
    w: ctx.W,
    h: ctx.H,
    fit: "cover",
    alt: "Emergency data exists, coordination is the gap",
  });
  return slide;
}
