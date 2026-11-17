const orders = [
  { id: "TL-1041", customer: "Mira Shah", status: "Packed", total: 780, invoice: 780 },
  { id: "TL-1042", customer: "Arun Vale", status: "In review", total: 1250, invoice: 1350 },
  { id: "TL-1043", customer: "Isha Rao", status: "Shipped", total: 640, invoice: 640 },
];
const money = amount => "₹" + amount.toLocaleString("en-IN");
const filter = document.querySelector("#filter");
if (filter) {
  function render() {
    const query = filter.value.trim().toLowerCase();
    const matches = orders.filter(order =>
      [order.id, order.customer, order.status].join(" ").toLowerCase().includes(query));
    const rows = document.querySelector("#rows");
    rows.replaceChildren();
    for (const order of matches) {
      const row = rows.insertRow();
      const link = document.createElement("a");
      link.href = "order.html?id=" + order.id;
      link.textContent = order.id;
      row.insertCell().append(link);
      for (const text of [order.customer, order.status, money(order.total)]) row.insertCell().textContent = text;
    }
    document.querySelector("#count").textContent = matches.length + (matches.length === 1 ? " order" : " orders");
  }
  filter.addEventListener("input", render);
  render();
} else {
  const order = orders.find(item => item.id === new URLSearchParams(location.search).get("id"));
  const detail = document.querySelector("#detail");
  if (order) {
    document.querySelector("#order").textContent = document.title = order.id;
    const list = document.createElement("dl");
    for (const [name, value] of Object.entries({"Customer": order.customer, "Status": order.status,
      "Order total": money(order.total), "Invoice total": money(order.invoice)})) {
      const term = document.createElement("dt");
      const desc = document.createElement("dd");
      term.textContent = name;
      desc.textContent = value;
      list.append(term, desc);
    }
    detail.append(list);
  } else detail.textContent = "Order not found.";
}
