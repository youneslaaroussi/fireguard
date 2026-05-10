export async function slide03(presentation, ctx) {
  const slide = presentation.slides.add();
  await ctx.addImage(slide, {
    path: new URL("../slides/slide-03-agent-loop.png", import.meta.url).pathname,
    x: 0,
    y: 0,
    w: ctx.W,
    h: ctx.H,
    fit: "cover",
    alt: "FireGuard signal to action system loop",
  });
  return slide;
}
