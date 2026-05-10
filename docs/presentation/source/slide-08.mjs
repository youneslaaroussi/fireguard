export async function slide08(presentation, ctx) {
  const slide = presentation.slides.add();
  await ctx.addImage(slide, {
    path: new URL("../slides/slide-08-close.png", import.meta.url).pathname,
    x: 0,
    y: 0,
    w: ctx.W,
    h: ctx.H,
    fit: "cover",
    alt: "FireGuard turns fragmented signals into coordinated action",
  });
  return slide;
}
