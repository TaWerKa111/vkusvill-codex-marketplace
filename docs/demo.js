(() => {
  'use strict';

  // The demo is intentionally local: illustrative prices, no catalog requests.
  const scenarios = {
    essentials: {
      prompt: 'Добавь молоко, 10 яиц и килограмм бананов',
      reply: 'Всё собрано. Количество можно изменить прямо в корзине.',
      detail: 'Учёл количество и фасовку',
      products: [
        { id: 'milk', name: 'Молоко 3,2%', pack: '1 л', price: 93, quantity: 1 },
        { id: 'eggs', name: 'Яйца С1', pack: '10 шт', price: 139, quantity: 1 },
        { id: 'banana', name: 'Бананы', pack: 'Цена за 1 кг', price: 199.9, quantity: 1, weight: true },
      ],
    },
    breakfast: {
      prompt: 'Собери завтрак на двоих. Молоко без лактозы',
      reply: 'Подобрал молоко без лактозы, овсянку и фрукты на двоих.',
      detail: 'Учёл пожелание: без лактозы',
      products: [
        { id: 'milk', name: 'Молоко без лактозы', pack: '1 л', price: 129, quantity: 1 },
        { id: 'oats', name: 'Хлопья овсяные', pack: '400 г', price: 89, quantity: 1 },
        { id: 'apple', name: 'Яблоки', pack: 'Цена за 1 кг', price: 169, quantity: .5, weight: true },
      ],
    },
    recipe: {
      prompt: 'Хочу сырники на четверых. Масло и мука есть',
      reply: 'Добавил творог, яйца и сахар. Масло и муку покупать не нужно.',
      detail: 'Ингредиенты дома не добавлял',
      products: [
        { id: 'curd', name: 'Творог 5%', pack: '200 г', price: 115, quantity: 3 },
        { id: 'eggs', name: 'Яйца С1', pack: '10 шт', price: 139, quantity: 1 },
        { id: 'sugar', name: 'Сахар белый', pack: '500 г', price: 69, quantity: 1 },
      ],
    },
  };

  const $ = selector => document.querySelector(selector);
  const list = $('#product-list');
  const money = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', minimumFractionDigits: 2 });
  const number = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const runningAnimations = new Set();
  const timers = new Set();
  let selected = 'essentials';
  let products = [];
  let running = false;
  let motionChoice = null;

  function motionEnabled() { return !reducedMotion.matches && motionChoice !== false; }

  function animate(element, delay = 0) {
    if (!motionEnabled() || !element.animate) return;
    const animation = element.animate([
      { opacity: 0, transform: 'translateY(8px)' },
      { opacity: 1, transform: 'translateY(0)' },
    ], { duration: 260, delay, easing: 'cubic-bezier(.2,.75,.25,1)', fill: 'backwards' });
    runningAnimations.add(animation);
    animation.finished.then(() => runningAnimations.delete(animation)).catch(() => runningAnimations.delete(animation));
  }

  function cancelPending() {
    timers.forEach(clearTimeout);
    timers.clear();
    runningAnimations.forEach(animation => animation.cancel());
    runningAnimations.clear();
    running = false;
  }

  function later(callback, ms) {
    const timer = setTimeout(() => { timers.delete(timer); callback(); }, ms);
    timers.add(timer);
  }

  function setStage(value) {
    document.querySelectorAll('[data-stage]').forEach((element, index) => {
      element.classList.toggle('is-current', index <= value);
    });
    $('#timeline-progress').style.transform = `scaleX(${(value + 1) / 3})`;
  }

  function sum() {
    return products.reduce((total, product) => total + Math.round(product.price * 100 * product.quantity), 0) / 100;
  }

  function updateTotal() {
    $('#basket-total').textContent = money.format(sum());
    $('#dialog-total').textContent = money.format(sum());
    const count = products.length;
    $('#item-count').textContent = `${count} ${count === 1 ? 'товар' : count > 1 && count < 5 ? 'товара' : 'товаров'}`;
    $('#demo-checkout').disabled = !count || running;
  }

  function renderProducts(withMotion = false) {
    list.replaceChildren();
    if (!products.length) {
      list.innerHTML = '<div class="basket-empty"><svg class="icon" aria-hidden="true"><use href="#i-basket"/></svg><span>Здесь появятся продукты</span></div>';
    }
    products.forEach((product, index) => {
      const row = document.createElement('div');
      row.className = 'product-row';
      row.dataset.product = product.id;
      // All product data comes from the constant scenarios above.
      row.innerHTML = `<div class="product-image" aria-hidden="true"><svg class="product-art"><use href="#p-${product.id}"/></svg></div><div><span class="product-name">${product.name}</span><span class="product-unit">${product.pack}</span></div><div><div class="product-price">${money.format(product.price * product.quantity)}</div><div class="quantity-controls"><button type="button" data-adjust="-1" aria-label="Уменьшить количество: ${product.name}"${product.quantity <= (product.weight ? .1 : 1) ? ' disabled' : ''}>−</button><output aria-label="Количество: ${product.name}">${number.format(product.quantity)}${product.weight ? ' кг' : ''}</output><button type="button" data-adjust="1" aria-label="Увеличить количество: ${product.name}"${product.quantity >= 10 ? ' disabled' : ''}>+</button></div></div>`;
      list.append(row);
      if (withMotion) animate(row, index * 45);
    });
    updateTotal();
  }

  function finish(withMotion = false) {
    running = false;
    products = scenarios[selected].products.map(product => ({ ...product }));
    $('#agent-reply').textContent = scenarios[selected].reply;
    $('#agent-detail span').textContent = scenarios[selected].detail;
    $('#agent-detail').style.opacity = '1';
    $('#demo-status').textContent = 'Готово. Можно менять количество или повторить подбор';
    setStage(2);
    renderProducts(withMotion);
  }

  function play(key = selected) {
    if (!Object.hasOwn(scenarios, key)) return;
    cancelPending();
    selected = key;
    document.querySelectorAll('[data-scenario]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.scenario === selected)));
    $('#demo-prompt').textContent = scenarios[selected].prompt;
    if (!motionEnabled()) { finish(); return; }
    running = true;
    products = [];
    setStage(0);
    $('#agent-reply').textContent = 'Принял запрос. Подбираю продукты и нужное количество.';
    $('#agent-detail').style.opacity = '0';
    $('#demo-status').textContent = 'Демонстрация: запрос передан агенту';
    renderProducts();
    animate($('#demo-prompt'));
    later(() => {
      setStage(1);
      $('#agent-reply').textContent = 'Сверяю пожелания, фасовку и количество.';
      $('#demo-status').textContent = 'Демонстрация: подбор подходящих товаров';
      animate($('.agent-message'));
    }, 650);
    later(() => finish(true), 1450);
  }

  list.addEventListener('click', event => {
    const button = event.target.closest('[data-adjust]');
    if (!button || running) return;
    const row = button.closest('[data-product]');
    const product = products.find(item => item.id === row.dataset.product);
    if (!product) return;
    const step = product.weight ? .1 : 1;
    product.quantity = Math.min(10, Math.max(step, Math.round((product.quantity + Number(button.dataset.adjust) * step) * 10) / 10));
    row.querySelector('.product-price').textContent = money.format(product.price * product.quantity);
    row.querySelector('output').textContent = `${number.format(product.quantity)}${product.weight ? ' кг' : ''}`;
    row.querySelector('[data-adjust="-1"]').disabled = product.quantity <= step;
    row.querySelector('[data-adjust="1"]').disabled = product.quantity >= 10;
    $('#demo-status').textContent = 'Количество изменено. Сумма пересчитана';
    updateTotal();
  });

  document.querySelectorAll('[data-scenario]').forEach(button => button.addEventListener('click', () => play(button.dataset.scenario)));
  $('#replay-demo').addEventListener('click', () => play());
  $('#hero-demo').addEventListener('click', () => play());
  document.querySelectorAll('[data-example]').forEach(button => button.addEventListener('click', () => {
    $('#demo').scrollIntoView({ behavior: motionEnabled() ? 'smooth' : 'instant', block: 'start' });
    play(button.dataset.example);
  }));

  function applyMotionPreference() {
    const enabled = motionEnabled();
    document.documentElement.dataset.motion = enabled ? 'on' : 'off';
    $('#motion-toggle').setAttribute('aria-pressed', String(enabled));
    $('#motion-toggle').setAttribute('aria-label', enabled ? 'Анимация включена. Нажмите, чтобы выключить' : reducedMotion.matches ? 'Анимация выключена настройкой уменьшения движения в системе' : 'Анимация выключена. Нажмите, чтобы включить');
    if (!enabled) {
      const wasRunning = running;
      cancelPending();
      if (wasRunning) finish();
    }
  }
  $('#motion-toggle').addEventListener('click', () => { motionChoice = !motionEnabled(); applyMotionPreference(); });
  reducedMotion.addEventListener('change', applyMotionPreference);

  // Timelines never keep running in an inactive tab or outside the viewport.
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && running) { cancelPending(); finish(); }
  });
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(entries => {
      if (!entries[0].isIntersecting && running) { cancelPending(); finish(); }
    }, { threshold: 0 }).observe($('#demo'));
  }

  const dialog = $('#checkout-dialog');
  $('#demo-checkout').addEventListener('click', () => {
    if (!products.length || running) return;
    $('#dialog-total').textContent = money.format(sum());
    dialog.showModal();
    animate(dialog);
  });
  $('#close-dialog').addEventListener('click', () => dialog.close());
  $('#dialog-install').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  });

  $('#copy-source').addEventListener('click', async () => {
    const source = $('#marketplace-source');
    try {
      await navigator.clipboard.writeText(source.textContent);
      $('#copy-status').textContent = 'Адрес скопирован';
    } catch {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(source);
      selection.removeAllRanges();
      selection.addRange(range);
      $('#copy-status').textContent = 'Адрес выделен — скопируйте его вручную';
    }
  });

  applyMotionPreference();
  finish();
})();
