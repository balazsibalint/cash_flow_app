

export default function App() {

  return (
    <div className="bg-slate-800 h-screen">
      <div className="pt-12 flex flex-col items-center justify-center">
        <h1 className="mb-8 text-5xl font-bold text-white">CashFlow App</h1>
        <input type="file" id="invoice" name="invoice" accept="application/pdf" multiple className="p-4 rounded-lg font-semibold text-lg bg-red-400 text-white"></input>
      </div>
    </div>
  )
}