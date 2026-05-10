export async function slide01(presentation, ctx) {
  const slide = presentation.slides.add();
  await ctx.addImage(slide, {
    path: new URL("../slides/slide-01-title.png", import.meta.url).pathname,
    x: 0,
    y: 0,
    w: ctx.W,
    h: ctx.H,
    fit: "cover",
    alt: "FireGuard title slide",
  });
  return slide;
}
