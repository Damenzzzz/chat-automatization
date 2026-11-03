import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function Home() {
  return (
    <main className="flex min-h-svh items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Satushy</CardTitle>
          <CardDescription>
            AI-консультант для вашего магазина в WhatsApp, Instagram, Telegram и на сайте.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Скоро здесь появятся лендинг и кабинет.
        </CardContent>
        <CardFooter>
          <Button disabled>Скоро</Button>
        </CardFooter>
      </Card>
    </main>
  );
}
