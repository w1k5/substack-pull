const gallery = document.querySelector('.tour-gallery');
const choices = [...gallery.querySelectorAll('.tour-picker button')];
const slides = choices.map((choice) => document.getElementById(choice.getAttribute('aria-controls')));
const position = document.getElementById('tour-position');
const description = document.getElementById('tour-description');
const lightbox = document.querySelector('.tour-lightbox');
const enlargedImage = lightbox.querySelector('img');
let current = 0;

function show(index, updateLink = false) {
  const imageHadFocus = slides[current].contains(document.activeElement);
  current = (index + slides.length) % slides.length;
  slides.forEach((slide, i) => {
    slide.hidden = i !== current;
    choices[i].setAttribute('aria-pressed', String(i === current));
  });
  position.textContent = `${current + 1} / ${slides.length}`;
  description.textContent = slides[current].querySelector('figcaption').textContent;
  if (updateLink) history.replaceState(null, '', `#${slides[current].id}`);
  if (imageHadFocus) slides[current].querySelector('.tour-shot').focus({ preventScroll: true });
}

function enlarge() {
  const image = slides[current].querySelector('img');
  enlargedImage.src = image.src;
  enlargedImage.alt = image.alt;
  document.getElementById('tour-lightbox-title').textContent = choices[current].textContent;
  lightbox.showModal();
  lightbox.querySelector('.tour-lightbox-image').scrollTo(0, 0);
}

choices.forEach((choice, i) => choice.addEventListener('click', () => show(i, true)));
document.getElementById('tour-previous').addEventListener('click', () => show(current - 1, true));
document.getElementById('tour-next').addEventListener('click', () => show(current + 1, true));
document.getElementById('tour-enlarge').addEventListener('click', enlarge);
document.getElementById('tour-close').addEventListener('click', () => lightbox.close());
lightbox.addEventListener('click', (event) => {
  if (event.target !== lightbox) return;
  const bounds = lightbox.getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right ||
      event.clientY < bounds.top || event.clientY > bounds.bottom) lightbox.close();
});
slides.forEach((slide) => slide.querySelector('.tour-shot').addEventListener('click', (event) => {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  enlarge();
}));
gallery.addEventListener('keydown', (event) => {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
  // Keep arrow keys available for scrolling the screenshot itself.
  if (event.target.closest('.tour-shot')) return;
  event.preventDefault();
  show(current + (event.key === 'ArrowRight' ? 1 : -1), true);
});
function showLinkedSlide() {
  const linked = slides.findIndex((slide) => '#' + slide.id === location.hash);
  show(linked < 0 ? 0 : linked);
}
window.addEventListener('hashchange', showLinkedSlide);
showLinkedSlide();
gallery.classList.add('is-ready');
gallery.querySelectorAll('[hidden]:not(.tour-slide)').forEach((element) => {
  element.hidden = false;
});
